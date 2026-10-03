"""单轮全成本聚合（T079，2026-10-03 用户需求 / R36）。

费用展示从"仅回答模型的 token 费"扩为**全成本**，包含此前隐形的三类：
- LLM 小调用：规划 / 扩检 / 时间解析（经 complete_chat，usage 精确，同官方分档定价）；
- 联网搜索：智谱按调用次数计费（search_std ¥0.01/次，其余档 ¥0.05/次，R36；失败不计费）；
- 检索设施：embedding（bge-m3 @ 硅基流动现免费 ¥0）+ 重排（Qwen3-Reranker-4B ¥0.14/M，按 tokens）。

实现：ContextVar 持有本回合的可变累加器——路由在回合开始 start_turn()，各调用点经 add_*()
累加（不在回合上下文里的调用，如入库管线的 embedding，静默跳过）；done 前读取快照。
不含：回写判定的后台 LLM/embedding 成本（发生在费用展示之后的异步任务；R36 备注）。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class TurnCost:
    llm_cny: float = 0.0
    web_cny: float = 0.0
    retrieval_cny: float = 0.0

    @property
    def total_cny(self) -> float:
        return self.llm_cny + self.web_cny + self.retrieval_cny

    def breakdown(self) -> dict:
        return {
            "llm": round(self.llm_cny, 6),
            "web": round(self.web_cny, 6),
            "retrieval": round(self.retrieval_cny, 6),
        }


_current: ContextVar[TurnCost | None] = ContextVar("turn_cost", default=None)


def start_turn() -> TurnCost:
    """回合开始：创建并绑定累加器（返回引用，供 done 前读快照）。"""
    turn = TurnCost()
    _current.set(turn)
    return turn


def current() -> TurnCost | None:
    return _current.get()


def add_llm(cny: float) -> None:
    turn = _current.get()
    if turn is not None and cny > 0:
        turn.llm_cny += cny


def add_web(cny: float) -> None:
    turn = _current.get()
    if turn is not None and cny > 0:
        turn.web_cny += cny


def add_retrieval(cny: float) -> None:
    turn = _current.get()
    if turn is not None and cny > 0:
        turn.retrieval_cny += cny
