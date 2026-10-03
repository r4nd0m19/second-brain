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
from datetime import datetime
from typing import Protocol, TypedDict
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.costing import add_llm


class ChatMessage(TypedDict):
    role: str  # system / user / assistant
    content: str


class StreamEvent(TypedDict, total=False):
    type: str  # "token" | "thinking" | "usage"
    text: str
    usage: dict


class LLMError(RuntimeError):
    """对话模型服务不可用 / 返回异常。"""


class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[ChatMessage], *, thinking: bool = False
    ) -> AsyncIterator[StreamEvent]:
        """流式生成：依次 yield token / thinking（思维链增量，仅思考档）/ usage 事件。"""

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
        transport: httpx.AsyncBaseTransport | None = None,  # 测试注入（MockTransport）
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport

    async def stream_chat(
        self, messages: list[ChatMessage], *, thinking: bool = False
    ) -> AsyncIterator[StreamEvent]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},  # 末尾块带回 token 计数（FR-017）
        }
        if thinking:  # 答案调用（T088）：开思考档——思维链经 reasoning_content 增量转发
            payload["thinking"] = {"type": "enabled"}
            if settings.llm_answer_effort:
                payload["effort"] = settings.llm_answer_effort
        else:  # 小调用（规划/扩检/时间解析）：显式关思考（V4 默认开启会吃满小 max_tokens 预算）
            payload["thinking"] = {"type": "disabled"}
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client, client.stream(
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
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content")  # 思维链增量（T088，思考档）
                    if reasoning:
                        yield {"type": "thinking", "text": reasoning}
                    content = delta.get("content")
                    if content:
                        yield {"type": "token", "text": content}


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
            "thinking": {"type": "disabled"},  # 规划器等工具调用：关思考防思维链吃满 max_tokens（T088）
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
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
    """收集流式输出为完整文本（时间解析等结构化小任务用；失败抛 LLMError）。

    顺带把该调用的 usage 计入本轮全成本（T079）——规划/扩检/时间解析等隐形小调用由此可见。
    """
    parts: list[str] = []
    async for event in client.stream_chat(messages):
        if event.get("type") == "token":
            parts.append(event.get("text", ""))
        elif event.get("type") == "usage":
            add_llm(estimate_cost_cny(event.get("usage") or {}))
    return "".join(parts)


def today_cn() -> str:
    """北京时间的今天（YYYY-MM-DD）——注入规划器/回答上下文，防模型凭训练记忆猜年份（T084）。"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _is_peak_now() -> bool:
    """高峰时段判定（北京时间周一至五 9:00-12:00、14:00-18:00；法定节假日未建模）。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.weekday() >= 5:
        return False
    return 9 <= now.hour < 12 or 14 <= now.hour < 18


def estimate_cost_cny(usage: dict) -> float:
    """按官方分档单价估算费用（FR-017 / R22）：缓存命中与未命中分开计价 + 峰谷倍率。"""
    peak = settings.price_peak_multiplier if _is_peak_now() else 1.0
    prompt = usage.get("prompt_tokens", 0)
    hit = usage.get("prompt_cache_hit_tokens", 0)
    miss = max(prompt - hit, 0)
    return (
        hit / 1_000_000 * settings.price_input_hit_per_million * peak
        + miss / 1_000_000 * settings.price_input_miss_per_million * peak
        + usage.get("completion_tokens", 0) / 1_000_000 * settings.price_output_per_million * peak
    )


def estimate_cost_cny_anthropic(usage: dict) -> float:
    """Anthropic 风格 usage → 费用（T086：DeepSeek 服务端搜索按 token 计，无按次费）。

    Anthropic 语义：input_tokens 不含缓存读取；缓存读取单列（缓存写入按未命中价计）。
    """
    cache_read = usage.get("cache_read_input_tokens") or 0
    return estimate_cost_cny(
        {
            "prompt_tokens": (usage.get("input_tokens") or 0)
            + cache_read
            + (usage.get("cache_creation_input_tokens") or 0),
            "prompt_cache_hit_tokens": cache_read,
            "completion_tokens": usage.get("output_tokens") or 0,
        }
    )


def get_llm_client() -> LLMClient:
    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
