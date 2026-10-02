"""对话模型客户端 —— OpenAI 兼容流式（默认 DeepSeek，可切任意兼容服务）。

失效降级语义（spec US2 场景 2）：抛 LLMError，由编排层转成 SSE `error` 事件 +
可重试；不影响已上传资料与历史对话。

流式事件（FR-017）：StreamEvent = {"type": "token", "text": ...}
                                | {"type": "usage", "usage": {...}}
usage 通过 stream_options.include_usage 请求（末尾块由服务端返回官方 token 计数）。
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


class StreamEvent(TypedDict, total=False):
    type: str  # "token" | "usage"
    text: str
    usage: dict


class LLMError(RuntimeError):
    """对话模型服务不可用 / 返回异常。"""


class LLMClient(Protocol):
    def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[StreamEvent]:
        """流式生成：依次 yield token / usage 事件。"""

    async def complete_with_tools(
        self, messages: list[dict], tools: list[dict], tool_choice: str = "auto"
    ) -> dict:
        """非流式 + 工具调用（F4 决策器用）：返回 {content, tool_calls:[{name, arguments}]}。"""


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

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[StreamEvent]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},  # 末尾块带回 token 计数（FR-017）
        }
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
                usage = obj.get("usage")
                if usage:
                    yield {"type": "usage", "usage": usage}
                choices = obj.get("choices") or []
                if choices:
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield {"type": "token", "text": delta}


    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
        max_tokens: int = 200,
    ) -> dict:
        """非流式请求（带 tools）：解析 OpenAI 兼容 tool_calls 为 {name, arguments}。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code != 200:
            body = response.text[:300]
            raise LLMError(f"对话模型返回 {response.status_code}: {body!r}")
        data = response.json()
        message = ((data.get("choices") or [{}])[0].get("message")) or {}
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append({"name": function.get("name") or "", "arguments": arguments})
        return {"content": message.get("content") or "", "tool_calls": tool_calls}


async def complete_chat(client: LLMClient, messages: list[ChatMessage]) -> str:
    """收集流式输出为完整文本（时间解析等结构化小任务用；失败抛 LLMError）。"""
    parts: list[str] = []
    async for event in client.stream_chat(messages):
        if event.get("type") == "token":
            parts.append(event.get("text", ""))
    return "".join(parts)


def estimate_cost_cny(usage: dict) -> float:
    """按配置单价估算费用（.env 可改；默认 deepseek 空闲时段价）。"""
    return (
        usage.get("prompt_tokens", 0) / 1_000_000 * settings.price_input_per_million
        + usage.get("completion_tokens", 0) / 1_000_000 * settings.price_output_per_million
    )


def get_llm_client() -> LLMClient:
    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
