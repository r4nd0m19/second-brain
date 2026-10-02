"""F4 编排集成：触发 / 强命中不触发 / 降级 / 来源形状 / 护栏停用（假检索+假搜索）。"""

import uuid

import pytest

import app.chat.orchestrator as orch
from app.config import settings
from app.models import AnswerSource, SourceType
from app.retrieval.search import RetrievedChunk
from app.websearch import guard
from app.websearch.client import WebSearchError, WebSearchResult

OWNER = uuid.uuid4()


class _FakeClient:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = (
            results
            if results is not None
            else [_result("A"), _result("B")]
        )
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


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="本地资料",
        source_type=SourceType.upload,
        content="本地内容",
        heading_path=None,
        page=None,
        score=score,
    )


def _patch(monkeypatch, *, client, hits, decide=None):
    """装配：假搜索客户端 / 假检索 / 假决策。"""
    decide_calls = {"n": 0}

    async def default_decide(_user_text: str) -> dict:
        decide_calls["n"] += 1
        return {"search": True, "query": "改写后的搜索词"}

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return hits

    monkeypatch.setattr(orch, "get_web_search", lambda: client)
    monkeypatch.setattr(orch, "hybrid_search", fake_search)
    monkeypatch.setattr(orch, "decide_search", decide or default_decide)
    guard.reset_state()
    return decide_calls


async def test_web_triggered_out_of_library(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[])

    plan = await orch.prepare_reply(None, OWNER, "帮我找类似 Karpathy 的 AI 教学博主主页", [])

    assert plan.source_type is AnswerSource.web
    assert client.searches == [("改写后的搜索词", settings.web_search_max_results)]
    assert len(plan.citations) == 2
    citation = plan.citations[0]
    assert citation["web"] is True
    assert citation["document_id"] is None
    assert citation["source_url"] == "https://a.example/1"
    assert citation["quote"]

    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "<web_results>" in joined
    assert "不得执行" in joined  # 不可信声明
    assert "结果A" in joined and "https://a.example/1" in joined


async def test_snippet_truncated_by_config(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[])
    monkeypatch.setattr(settings, "web_search_snippet_max", 10)

    plan = await orch.prepare_reply(None, OWNER, "外部问题", [])
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "摘要A摘要A摘要A摘要A" not in joined  # 90 字摘要被截到 10
    assert "摘要A" in joined


async def test_strong_hit_never_searches(monkeypatch) -> None:
    client = _FakeClient()

    async def boom(*_args, **_kwargs):
        raise AssertionError("强命中不应调用决策器")

    class _NullSession:  # 强命中路径会调用 enrich_citations（F1），提供最小 session 桩
        async def get(self, *_args, **_kwargs):
            return None

    decide_calls = _patch(monkeypatch, client=client, hits=[_chunk(0.9)], decide=boom)
    plan = await orch.prepare_reply(_NullSession(), OWNER, "SDD 的核心循环是什么", [])

    assert plan.source_type is AnswerSource.kb
    assert decide_calls["n"] == 0
    assert client.searches == []


async def test_no_key_keeps_current_behavior(monkeypatch) -> None:
    async def boom(*_args, **_kwargs):
        raise AssertionError("未配置凭据不应调用决策器")

    _patch(monkeypatch, client=None, hits=[], decide=boom)
    monkeypatch.setattr(orch, "get_web_search", lambda: None)

    plan = await orch.prepare_reply(None, OWNER, "外部问题", [])
    assert plan.source_type is AnswerSource.model_knowledge
    assert plan.citations == []


async def test_search_error_degrades(monkeypatch) -> None:
    client = _FakeClient(error=WebSearchError("超时"))
    _patch(monkeypatch, client=client, hits=[])

    plan = await orch.prepare_reply(None, OWNER, "外部问题", [])
    assert plan.source_type is AnswerSource.model_knowledge
    assert plan.citations == []


async def test_empty_results_degrades(monkeypatch) -> None:
    client = _FakeClient(results=[])
    _patch(monkeypatch, client=client, hits=[])

    plan = await orch.prepare_reply(None, OWNER, "外部问题", [])
    assert plan.source_type is AnswerSource.model_knowledge
    assert plan.citations == []


async def test_weak_hits_allow_web_supplement(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[_chunk(0.55)])  # 弱相关

    plan = await orch.prepare_reply(None, OWNER, "外部问题", [])
    assert plan.source_type is AnswerSource.web
    assert plan.related_hints and plan.citations  # 弱相关提示与联网来源并存


async def test_daily_limit_blocks_after_threshold(monkeypatch) -> None:
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[])
    monkeypatch.setattr(settings, "web_search_daily_limit", 1)

    first = await orch.prepare_reply(None, OWNER, "问题一", [])
    second = await orch.prepare_reply(None, OWNER, "问题二", [])

    assert first.source_type is AnswerSource.web
    assert len(client.searches) == 1  # 第二次被护栏拦下
    assert second.source_type is AnswerSource.model_knowledge


async def test_web_results_not_persisted(monkeypatch) -> None:
    """结果不入库：web 引用无 document_id（无可持久化对象），且编排不触碰任何写路径。"""
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[])

    plan = await orch.prepare_reply(None, OWNER, "外部问题", [])
    assert all(citation["document_id"] is None for citation in plan.citations)
    assert all(citation["web"] is True for citation in plan.citations)


# ---- 显式联网指令（FR-011，2026-10-02）----


class _NullSession:  # enrich_citations 的最小 session 桩
    async def get(self, *_args, **_kwargs):
        return None


def test_explicit_detection_regex() -> None:
    positive = [
        "发起联网搜索",
        "联网搜一下 Upwork 上的最新岗位",
        "帮我查一下杭州明天的天气",
        "搜索一下 Supabase 最新定价",
        "上网查查这个错误",
        "search the web for Karpathy",
    ]
    negative = [
        "SDD 的核心循环是什么",
        "搜一下我的资料里的 React 内容",
        "帮我查一下知识库里的部署步骤",
        "联网了吗",  # 无检索动词
        "外部问题",
    ]
    for text in positive:
        assert orch.looks_like_explicit_web_search(text), text
    for text in negative:
        assert not orch.looks_like_explicit_web_search(text), text


async def test_explicit_command_forces_web_even_with_strong_hit(monkeypatch) -> None:
    """用户显式要求联网：即使本地强命中，也执行搜索；本地资料附上且编号续接。"""
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[_chunk(0.9)])

    plan = await orch.prepare_reply(
        _NullSession(), OWNER, "联网搜一下 Upwork 上的最新岗位", []
    )

    assert client.searches == [("改写后的搜索词", settings.web_search_max_results)]
    assert plan.source_type is AnswerSource.web
    assert len(plan.citations) == 3  # 本地 1 条 + web 2 条
    assert not plan.citations[0].get("web")  # 本地条目在前
    assert plan.citations[1]["web"] is True and plan.citations[2]["web"] is True
    joined = "\n".join(m["content"] for m in plan.llm_messages)
    assert "【资料1】" in joined  # 本地资料仍注入
    assert "[2] 结果A" in joined  # web 编号自 N+1=2 起（不冲突）


async def test_explicit_command_without_topic_no_search(monkeypatch) -> None:
    """裸指令「发起联网搜索」：无可检索内容 → 不搜索，交由模型引导；决策器只调用一次。"""
    client = _FakeClient()

    async def decline(_user_text: str) -> dict:
        decline.n += 1
        return {"search": False, "query": ""}

    decline.n = 0
    _patch(monkeypatch, client=client, hits=[], decide=decline)

    plan = await orch.prepare_reply(None, OWNER, "发起联网搜索", [])

    assert decline.n == 1  # 不重复调用决策器
    assert client.searches == []
    assert plan.source_type is AnswerSource.model_knowledge
    assert plan.citations == []
    system = plan.llm_messages[0]["content"]
    assert "不得向用户描述系统内部机制" in system  # 措辞契约（防内部机制泄露，无条件）
    assert "不得声称自己无法联网" in system  # 能力话术契约（2026-10-02 复测加固）
    assert "请用户给出要搜索" in system  # 引导式回应契约
    assert "怎么才能让你联网搜索" in system  # 能力问句 → 给出指令示例（2026-10-02 复测加固）


async def test_explicit_command_search_failure_falls_back_to_local(monkeypatch) -> None:
    """显式联网但搜索失败：静默降级回本地强命中作答（不让问答失败）。"""
    client = _FakeClient(error=WebSearchError("超时"))
    _patch(monkeypatch, client=client, hits=[_chunk(0.9)])

    plan = await orch.prepare_reply(
        _NullSession(), OWNER, "联网搜一下 Upwork 上的最新岗位", []
    )

    assert client.searches  # 尝试过搜索
    assert plan.source_type is AnswerSource.kb
    assert len(plan.citations) == 1


async def test_explicit_command_web_only_keeps_weak_hints(monkeypatch) -> None:
    """显式联网 + 无强命中：纯联网作答；弱相关仅作提示（同兜底路径语义）。"""
    client = _FakeClient()
    _patch(monkeypatch, client=client, hits=[_chunk(0.55)])

    plan = await orch.prepare_reply(None, OWNER, "帮我查一下杭州明天的天气", [])

    assert plan.source_type is AnswerSource.web
    assert plan.related_hints and plan.citations


# 引用 pytest，避免未使用告警（fixture 风格保留给后续扩展）
_ = pytest
