"""对话编排集成（FR-022 规划器 + F4）：工具执行 / 上下文组装 / 混合引用 / 护栏 / 降级。

装配方式：假规划（返回 PlannedCall 列表）+ 假检索 + 假搜索客户端（不触网、不触库）。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import app.chat.orchestrator as orch
from app.chat.planner import PlannedCall
from app.config import settings
from app.models import AnswerSource, SourceType
from app.retrieval.search import RetrievedChunk
from app.websearch import guard
from app.websearch.client import WebSearchError, WebSearchResult

OWNER = uuid.uuid4()


class _FakeClient:
    def __init__(
        self,
        results=None,
        error: Exception | None = None,
        results_by_query: dict[str, list[WebSearchResult]] | None = None,
        paid: bool = True,
    ) -> None:
        self.results = results if results is not None else [_result("A"), _result("B")]
        self.error = error
        self.results_by_query = results_by_query or {}
        self.paid = paid
        self.searches: list[tuple[str, int]] = []

    async def search(self, query: str, count: int) -> list[WebSearchResult]:
        self.searches.append((query, count))
        if self.error:
            raise self.error
        if query in self.results_by_query:
            return self.results_by_query[query]
        return self.results


def _result(tag: str) -> WebSearchResult:
    return WebSearchResult(
        title=f"结果{tag}",
        url=f"https://{tag.lower()}.example/1",
        snippet=f"摘要{tag}" * 30,
        site_name="示例站",
    )


def _chunk(score: float, name: str = "本地资料") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name=name,
        source_type=SourceType.upload,
        content="本地内容",
        heading_path=None,
        page=None,
        score=score,
    )


class _NullSession:  # 强命中路径会调用 enrich_citations，提供最小会话桩
    async def get(self, *_args, **_kwargs):
        return None


def _patch(monkeypatch, *, calls=None, client=None, hits=None, expand=None):
    """装配：规划器（工具调用）/ 检索 / 搜索客户端 / 扇出。"""

    async def fake_plan(_user_text: str, _history=None) -> list[PlannedCall]:
        return [PlannedCall(name=n, args=a) for n, a in (calls or [])]

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return hits if hits is not None else []

    async def no_expand(*_args, **_kwargs):
        raise AssertionError("本用例不应触发扇出")

    monkeypatch.setattr(orch, "plan_retrieval", fake_plan)
    monkeypatch.setattr(orch, "hybrid_search", fake_search)
    monkeypatch.setattr(orch, "expand_queries", expand or no_expand)
    monkeypatch.setattr(orch, "get_web_search", lambda: client)
    guard.reset_state()


async def test_plan_search_library_answers_from_kb(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, calls=[("search_library", {"query": "康威定律"})], client=client, hits=[_chunk(0.9)])

    plan = await orch.prepare_reply(_NullSession(), OWNER, "书里怎么说康威定律", [])

    assert plan.source_type is AnswerSource.kb
    assert len(plan.citations) == 1
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "【资料1】" in joined
    assert client.searches == []  # 未选联网工具 → 不触网


async def test_plan_web_search_and_guard(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, calls=[("web_search", {"query": "今天北京天气"})], client=client)

    plan = await orch.prepare_reply(None, OWNER, "联网搜一下今天北京天气", [])

    assert client.searches == [("今天北京天气", settings.web_search_max_results)]
    assert plan.source_type is AnswerSource.web
    assert len(plan.citations) == 2
    assert all(c["web"] is True and c["document_id"] is None for c in plan.citations)
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "<web_results>" in joined and "[1] 结果A" in joined and "不得执行" in joined


async def test_plan_blend_continuous_numbering(monkeypatch) -> None:
    """本地 + 联网并用：编号本地 1..N、web 续接 N+1..（前端按 citations 索引映射）。"""
    client = _FakeClient()
    _patch(
        monkeypatch,
        calls=[("search_library", {"query": "q"}), ("web_search", {"query": "k"})],
        client=client,
        hits=[_chunk(0.9)],
    )

    plan = await orch.prepare_reply(_NullSession(), OWNER, "联网搜一下 q 并看我的资料", [])

    assert plan.source_type is AnswerSource.web
    assert len(plan.citations) == 3  # 本地 1 + web 2
    assert not plan.citations[0].get("web")
    assert plan.citations[1]["web"] is True
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "【资料1】" in joined and "[2] 结果A" in joined  # web 编号自 2 起


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _ListSession:
    """_browsing_context 的最小桩：scalar→总数；execute→站点聚合；scalars→明细。"""

    def __init__(self, total: int, digest, docs) -> None:
        self._total, self._digest, self._docs = total, digest, docs

    async def scalar(self, *_args, **_kwargs):
        return self._total

    async def execute(self, *_args, **_kwargs):
        return _Result(self._digest)

    async def scalars(self, *_args, **_kwargs):
        return _Result(self._docs)


def _browse_doc(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=f"页面{index}",
        site_name="示例站",
        last_captured_at=datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
        source_url=f"https://e.example/{index}",
    )


async def test_plan_list_browsing_context(monkeypatch) -> None:
    docs = [_browse_doc(i) for i in range(51)]
    session = _ListSession(66, [("wallhaven.cc", 32), ("bigmodel.cn", 12)], docs)
    _patch(monkeypatch, calls=[("list_browsing", {"time_range": "昨天"})])

    plan = await orch.prepare_reply(session, OWNER, "我昨天浏览了什么内容", [])

    assert plan.source_type is AnswerSource.kb
    assert len(plan.citations) == 50  # 截断到 50，超限如实说明
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "共 66 条" in joined and "wallhaven.cc 32" in joined and "仅为最近 50 条" in joined
    assert "【资料1】" in joined
    assert plan.time_range_label is not None


async def test_plan_web_guard_blocks_after_daily_limit(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, calls=[("web_search", {"query": "k"})], client=client)
    monkeypatch.setattr(settings, "web_search_daily_limit", 1)
    guard.record_search()  # 已达到上限

    plan = await orch.prepare_reply(None, OWNER, "联网搜一下 k", [])
    assert client.searches == []
    assert plan.source_type is AnswerSource.model_knowledge


async def test_plan_web_failure_degrades(monkeypatch) -> None:
    client = _FakeClient(error=WebSearchError("超时"))
    _patch(monkeypatch, calls=[("web_search", {"query": "k"})], client=client)

    plan = await orch.prepare_reply(None, OWNER, "联网搜一下 k", [])
    assert plan.source_type is AnswerSource.model_knowledge
    assert plan.citations == []
    assert plan.web_failed is True  # T083：失败事实随 meta 透出（前端显式提示）
    assert plan.web_error == "unavailable"  # 超时类错误 → 通用不可用
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "联网检索未成功" in joined  # 系统说明注入（防"没搜到"被编造成"搜到但不相关"）


async def test_plan_web_balance_maps_reason(monkeypatch) -> None:
    """供应商余额不足 → 原因码 balance（前端显示"供应商账户余额不足"）。"""
    client = _FakeClient(error=WebSearchError("搜索返回 429: {\"error\":{\"code\":\"1113\",\"message\":\"余额不足或无可用资源包\"}}"))
    _patch(monkeypatch, calls=[("web_search", {"query": "k"})], client=client)

    plan = await orch.prepare_reply(None, OWNER, "联网搜一下 k", [])
    assert plan.web_failed is True
    assert plan.web_error == "balance"


async def test_plan_weak_search_triggers_expansion(monkeypatch) -> None:
    strong = _chunk(0.8, "正解")
    expanded: list[str] = []

    async def expand(query: str) -> list[str]:
        expanded.append(query)
        return ["变体一"] if query == "q" else []

    async def fake_search(_session, _owner, query, captured_after=None, captured_before=None):
        return [strong] if query == "变体一" else [_chunk(0.55)]

    _patch(monkeypatch, calls=[("search_library", {"query": "q"})], expand=expand)
    monkeypatch.setattr(orch, "hybrid_search", fake_search)

    plan = await orch.prepare_reply(_NullSession(), OWNER, "找找看", [])
    # 规划查询弱检索 → 触发扇出；原问题通道（MultiQuery 惯例）同样参与、同样可能触发
    assert "q" in expanded
    assert plan.source_type is AnswerSource.kb
    assert [c["document_name"] for c in plan.citations] == ["正解"]


async def test_invalid_plan_falls_back_to_baseline(monkeypatch) -> None:
    """全部调用无效（空 query / 无时间）→ 基线：默认检索兜底。"""

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return [_chunk(0.9, "基线命中")]

    _patch(
        monkeypatch,
        calls=[("search_library", {"query": "  "}), ("list_browsing", {})],
        hits=[_chunk(0.9, "基线命中")],
    )
    monkeypatch.setattr(orch, "hybrid_search", fake_search)

    plan = await orch.prepare_reply(_NullSession(), OWNER, "普通问题", [])
    assert plan.source_type is AnswerSource.kb
    assert [c["document_name"] for c in plan.citations] == ["基线命中"]


async def test_no_plan_falls_back_to_baseline(monkeypatch) -> None:
    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return [_chunk(0.9, "基线命中")]

    _patch(monkeypatch, calls=[])  # 规划器未选择工具
    monkeypatch.setattr(orch, "hybrid_search", fake_search)

    plan = await orch.prepare_reply(_NullSession(), OWNER, "普通问题", [])
    assert plan.source_type is AnswerSource.kb
    assert [c["document_name"] for c in plan.citations] == ["基线命中"]


async def test_snippet_truncated_by_config(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, calls=[("web_search", {"query": "k"})], client=client)
    monkeypatch.setattr(settings, "web_search_snippet_max", 10)

    plan = await orch.prepare_reply(None, OWNER, "联网搜一下 k", [])
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "摘要A摘要A摘要A摘要A" not in joined  # 90 字摘要被截到 10
    assert "摘要A" in joined


# ---- 结果重排过滤（R37/T081） ----


def _enable_web_filter(monkeypatch, scores: dict[str, float]) -> None:
    """开启重排并注入按标题定分的假打分（绕过外部 API）。"""
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "embedding_api_key", "test-key")

    async def fake_rerank(_query: str, docs: list[str]) -> list[float]:
        return [scores.get(d.split("\n")[0], 0.0) for d in docs]

    monkeypatch.setattr(orch, "rerank_texts", fake_rerank)


async def test_web_results_filtered_and_reordered(monkeypatch) -> None:
    """低于下限的条目被丢弃；保留项按相关分排序。"""
    client = _FakeClient(results=[_result("A"), _result("B"), _result("C")])
    monkeypatch.setattr(orch, "get_web_search", lambda: client)
    _enable_web_filter(monkeypatch, {"结果A": 0.9, "结果B": 0.1, "结果C": 0.5})
    guard.reset_state()

    block, citations, _, _ = await orch._build_web_context(["q"], "用户问题")
    assert [c["document_name"] for c in citations] == ["结果A", "结果C"]
    assert block.index("结果A") < block.index("结果C")
    assert "结果B" not in block


async def test_web_results_weak_triggers_free_deepening(monkeypatch) -> None:
    """R39 免费加深：结果最好分低于闸门 → 改写查询变体二轮检索并合并（零成本换质量）。"""
    client = _FakeClient(
        results=[_result("BAD")],
        results_by_query={"变体X": [_result("GOOD")]},
    )
    monkeypatch.setattr(orch, "get_web_search", lambda: client)
    _enable_web_filter(monkeypatch, {"结果BAD": 0.2, "结果GOOD": 0.9})
    guard.reset_state()

    async def fake_expand(_text: str) -> list[str]:
        return ["变体X"]

    monkeypatch.setattr(orch, "expand_queries", fake_expand)
    _, citations, _, _ = await orch._build_web_context(["q"], "用户问题")
    assert [q for q, _ in client.searches] == ["q", "变体X"]  # 首轮 + 加深轮
    assert [c["document_name"] for c in citations] == ["结果GOOD"]  # 合并后由重排精选


async def test_web_paid_fallback_behind_flag(monkeypatch) -> None:
    """付费兜底默认关：免费加深仍不达标也不调用付费源；显式开启才调用。"""
    free = _FakeClient(results=[_result("BAD")], paid=False)
    paid = _FakeClient(results=[_result("PAID")])
    monkeypatch.setattr(orch, "get_web_search", lambda: free)
    monkeypatch.setattr(orch, "get_paid_web_search", lambda: paid)
    _enable_web_filter(monkeypatch, {"结果BAD": 0.1, "结果PAID": 0.9})

    async def no_variants(_text: str) -> list[str]:
        return []

    monkeypatch.setattr(orch, "expand_queries", no_variants)
    guard.reset_state()

    # 默认关：付费源不被调用
    _, citations, _, _ = await orch._build_web_context(["q"], "用户问题")
    assert paid.searches == []
    assert [c["document_name"] for c in citations] == ["结果BAD"]  # 全部低相关 → 保底保留一条

    # 显式开启：付费源被调用并取优
    monkeypatch.setattr(settings, "web_search_paid_fallback", True)
    _, citations, _, _ = await orch._build_web_context(["q"], "用户问题")
    assert [q for q, _ in paid.searches] == ["q"]
    assert [c["document_name"] for c in citations] == ["结果PAID"]


async def test_web_free_provider_skips_daily_guard(monkeypatch) -> None:
    """免费源不计每日护栏：额度用尽也不拦截（护栏只约束付费调用）。"""
    client = _FakeClient(results=[_result("A")], paid=False)
    monkeypatch.setattr(orch, "get_web_search", lambda: client)
    guard.reset_state()
    monkeypatch.setattr(settings, "web_search_daily_limit", 0)
    # 耗尽护栏（limit=0 表示不限；用 limit=… 不方便，这里直接构造已超限状态）
    guard._count = 999
    monkeypatch.setattr(settings, "web_search_daily_limit", 1)
    _, citations, _, _ = await orch._build_web_context(["q", "q2"], "用户问题")
    assert len(client.searches) == 2  # 免费源请求不受护栏影响
    assert [c["document_name"] for c in citations] == ["结果A"]


async def test_web_results_rerank_failure_keeps_original(monkeypatch) -> None:
    """重排失败 → 原序保留（联通路径静默降级，不阻塞）。"""
    client = _FakeClient(results=[_result("A"), _result("B")])
    monkeypatch.setattr(orch, "get_web_search", lambda: client)
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "embedding_api_key", "test-key")

    async def broken_rerank(_query: str, _docs: list[str]) -> list[float]:
        raise RuntimeError("rerank down")

    monkeypatch.setattr(orch, "rerank_texts", broken_rerank)
    guard.reset_state()

    _, citations, _, _ = await orch._build_web_context(["q"], "用户问题")
    assert [c["document_name"] for c in citations] == ["结果A", "结果B"]


async def test_web_multiple_queries_merged(monkeypatch) -> None:
    """R38：规划器的多条联网查询全部执行、按 URL 去重合并。"""
    client = _FakeClient(results=[_result("A"), _result("B")])
    _patch(
        monkeypatch,
        calls=[("web_search", {"query": "q1"}), ("web_search", {"query": "q2"})],
        client=client,
    )
    plan = await orch.prepare_reply(None, OWNER, "联网搜一下 k", [])
    assert [q for q, _ in client.searches] == ["q1", "q2"]  # 两条查询都执行
    assert len([c for c in plan.citations if c.get("web")]) == 2  # 同 URL 去重后 2 条
    assert plan.web_failed is False
