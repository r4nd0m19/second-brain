"""低置信多查询重试（FR-021/R19）：变体解析 + 编排扩检行为（改写失败静默）。"""

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
    async def no_plan(_user_text: str) -> list:
        return []  # 规划器未选择工具 → 走基线路径（本组用例聚焦既有检索行为）

    monkeypatch.setattr(orch, "plan_retrieval", no_plan)
    monkeypatch.setattr(orch, "hybrid_search", search)
    monkeypatch.setattr(orch, "expand_queries", expand)
    monkeypatch.setattr(orch, "get_web_search", lambda: None)
    guard.reset_state()


async def test_low_confidence_expansion_rescues_strong_hit(monkeypatch) -> None:
    """弱命中 → 扇出变体召回强命中 → 走 kb 路径且出处含变体召回文档。"""
    weak = _chunk(0.55, "弱资料")
    strong = _chunk(0.8, "正解")
    seen_queries: list[str] = []

    async def fake_search(_session, _owner, query, captured_after=None, captured_before=None):
        seen_queries.append(query)
        return {"低置信问题": [weak], "变体一": [strong]}.get(query, [])

    async def fake_expand(q: str) -> list[str]:
        assert q == "低置信问题"
        return ["变体一"]

    _patch(monkeypatch, search=fake_search, expand=fake_expand)

    plan = await orch.prepare_reply(_NullSession(), OWNER, "低置信问题", [])

    assert plan.source_type is AnswerSource.kb
    assert [c["document_name"] for c in plan.citations] == ["正解"]
    assert seen_queries == ["低置信问题", "变体一"]


def test_referential_splice_rules() -> None:
    """T039 改造（2026-10-03）：拼接仅作低置信候选——纯函数规则。"""
    history = [{"role": "user", "content": "康威定律是什么？"}]
    assert orch._referential_splice("书里怎么说的？", history) == "康威定律是什么？ 书里怎么说的？"
    assert orch._referential_splice("那本书里关于它的部分讲了什么", history) is not None
    # 长且无指代词 → 不拼接；无历史 → 不拼接；与上轮相同 → 不拼接
    assert orch._referential_splice("光合作用的暗反应阶段发生在叶绿体的基质中请详细说明", history) is None
    assert orch._referential_splice("短问题", []) is None
    assert orch._referential_splice("康威定律是什么？", history) is None


async def test_short_new_question_not_polluted_by_history(monkeypatch) -> None:
    """实测修复：自足强命中（「游戏循环怎么实现」0.624）不得被上一轮话题拼接稀释（0.594 跌破阈值）。"""
    queries: list[str] = []

    async def fake_search(_session, _owner, query, captured_after=None, captured_before=None):
        queries.append(query)
        return [_chunk(0.62, "游戏引擎书")]

    async def boom(*_args, **_kwargs):
        raise AssertionError("强命中不应触发重试/拼接")

    _patch(monkeypatch, search=fake_search, expand=boom)
    history = [{"role": "user", "content": "架构书里分层架构是怎么讲的？"}]

    plan = await orch.prepare_reply(_NullSession(), OWNER, "游戏循环怎么实现", history)

    assert plan.source_type is AnswerSource.kb
    assert queries == ["游戏循环怎么实现"]  # 未经拼接、未重试


async def test_weak_referential_followup_splices_in_retry(monkeypatch) -> None:
    """指代性追问低置信时，拼接上一轮问题的版本作为候选参与重试并救回。"""
    strong = _chunk(0.8, "康威定律所在章节")
    seen: list[str] = []

    async def fake_search(_session, _owner, query, captured_after=None, captured_before=None):
        seen.append(query)
        return [strong] if query == "康威定律是什么？ 书里怎么说的？" else []

    async def no_variants(_query: str) -> list[str]:
        return []

    _patch(monkeypatch, search=fake_search, expand=no_variants)
    history = [{"role": "user", "content": "康威定律是什么？"}]

    plan = await orch.prepare_reply(_NullSession(), OWNER, "书里怎么说的？", history)

    assert plan.source_type is AnswerSource.kb
    assert "康威定律是什么？ 书里怎么说的？" in seen


async def test_strong_hit_skips_expansion(monkeypatch) -> None:
    async def boom(*_args, **_kwargs):
        raise AssertionError("强命中不应触发扩检")

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return [_chunk(0.9, "强资料")]

    _patch(monkeypatch, search=fake_search, expand=boom)
    plan = await orch.prepare_reply(_NullSession(), OWNER, "普通问题", [])
    assert plan.source_type is AnswerSource.kb


async def test_expansion_failure_keeps_existing_behavior(monkeypatch) -> None:
    """改写无有效变体 → 与原行为一致：无强命中且无联网 → model_knowledge。"""

    async def fake_search(_session, _owner, _query, captured_after=None, captured_before=None):
        return [_chunk(0.4)]

    async def empty_expand(_q: str) -> list[str]:
        return []

    _patch(monkeypatch, search=fake_search, expand=empty_expand)
    plan = await orch.prepare_reply(None, OWNER, "低置信问题", [])
    assert plan.source_type is AnswerSource.model_knowledge
