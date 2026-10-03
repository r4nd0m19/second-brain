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
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = results if results is not None else [_result("A"), _result("B")]
        self.error = error
        self.searches: list[tuple[str, int]] = []

    async def search(self, query: str, count: int) -> list[WebSearchResult]:
        self.searches.append((query, count))
        if self.error:
            raise self.error
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
