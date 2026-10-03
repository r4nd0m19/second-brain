"""检索改写与扇出退役回归（FR-021/R19 → T077）：变体解析（联网免费加深仍用）+ 低置信不再扩检。"""

import uuid

import app.chat.orchestrator as orch
from app.chat.llm import LLMError
from app.models import AnswerSource, SourceType
from app.retrieval import rewrite
from app.retrieval.search import RetrievedChunk
from app.websearch import guard

OWNER = uuid.uuid4()


def _chunk(score: float, name: str = "资料") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name=name,
        source_type=SourceType.upload,
        content="内容",
        heading_path=None,
        page=None,
        score=score,
    )


class _NullSession:  # 强命中路径会调用 enrich_citations，提供最小会话桩
    async def get(self, *_args, **_kwargs):
        return None


# ---- 变体解析 ----


async def test_expand_queries_parses_and_caps(monkeypatch) -> None:
    async def fake_complete(_client, _messages):
        return "1. 变体一\n- 变体二\n变体三\n变体四\n\n"

    monkeypatch.setattr(rewrite, "complete_chat", fake_complete)
    monkeypatch.setattr(rewrite, "get_llm_client", lambda: None)

    variants = await rewrite.expand_queries("原始问题")
    assert variants == ["变体一", "变体二", "变体三"]  # 上限 3、去编号/符号


async def test_expand_queries_failure_returns_empty(monkeypatch) -> None:
    async def boom(_client, _messages):
        raise LLMError("x")

    monkeypatch.setattr(rewrite, "complete_chat", boom)
    monkeypatch.setattr(rewrite, "get_llm_client", lambda: None)
    assert await rewrite.expand_queries("原始问题") == []


async def test_expand_queries_excludes_echo(monkeypatch) -> None:
    async def fake_complete(_client, _messages):
        return "原始问题\n换个说法的问题"

    monkeypatch.setattr(rewrite, "complete_chat", fake_complete)
    monkeypatch.setattr(rewrite, "get_llm_client", lambda: None)
    assert await rewrite.expand_queries("原始问题") == ["换个说法的问题"]


# ---- 编排扩检 ----


def _patch(monkeypatch, *, search, expand) -> None:
    async def no_plan(_user_text: str, _history=None) -> list:
        return []  # 规划器未选择工具 → 走基线路径（本组用例聚焦既有检索行为）

    monkeypatch.setattr(orch, "plan_retrieval", no_plan)
    monkeypatch.setattr(orch, "hybrid_search", search)
    monkeypatch.setattr(orch, "expand_queries", expand)
    monkeypatch.setattr(orch, "get_web_search", lambda: None)
    guard.reset_state()


async def test_low_confidence_no_longer_expands(monkeypatch) -> None:
    """T077 退役回归：弱命中不再扇出——变体不得被调用、弱命中不升格 kb（走兜底 + related_hints）。"""
    weak = _chunk(0.55, "弱资料")
    seen_queries: list[str] = []

    async def fake_search(_session, _owner, query, captured_after=None, captured_before=None):
        seen_queries.append(query)
        return [weak]

    async def boom_expand(_q: str) -> list[str]:
        raise AssertionError("扇出已退役（T077）：不应调用 expand_queries")

    _patch(monkeypatch, search=fake_search, expand=boom_expand)

    plan = await orch.prepare_reply(_NullSession(), OWNER, "低置信问题", [])

    assert seen_queries == ["低置信问题"]  # 仅原问题一次检索，无变体
    assert plan.source_type is AnswerSource.model_knowledge  # 弱命中不再升格 kb
    assert plan.citations == []
    assert [c["document_name"] for c in plan.related_hints] == ["弱资料"]


async def test_strong_hit_skips_expansion(monkeypatch) -> None:
    async def boom(*_args, **_kwargs):
        raise AssertionError("强命中不应触发扩检")

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return [_chunk(0.9, "强资料")]

    _patch(monkeypatch, search=fake_search, expand=boom)
    plan = await orch.prepare_reply(_NullSession(), OWNER, "普通问题", [])
    assert plan.source_type is AnswerSource.kb


async def test_pure_fallback_question_no_expansion(monkeypatch) -> None:
    """库外问题（0.4 < 弱线）→ 直接兜底：不扩检、无 related_hints（T077 退役回归）。"""

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return [_chunk(0.4)]

    async def boom_expand(_q: str) -> list[str]:
        raise AssertionError("扇出已退役（T077）：不应调用 expand_queries")

    _patch(monkeypatch, search=fake_search, expand=boom_expand)
    plan = await orch.prepare_reply(None, OWNER, "低置信问题", [])
    assert plan.source_type is AnswerSource.model_knowledge
    assert plan.related_hints == []
