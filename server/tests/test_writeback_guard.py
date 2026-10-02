"""回写自污染防护（2026-10-02 实测驱动）：失败回答（找不到/无权限）不回写。

背景：模型「找不到 / 没有访问权限」类回答被回写后，会成为同类问题检索的最高分命中
（jasonL 查询被「没有找到 jasonL」的回答 0.73 顶置，形成闭环误导；见 001 research R18）。
"""

from app.chat.writeback import is_no_info_answer


def test_no_info_answers_are_skipped() -> None:
    assert is_no_info_answer(
        "我核对了手上的资料，没有找到任何叫「jasonL」的用户信息，也没有你的技术栈记录。"
    )
    assert is_no_info_answer("我无法确认你最近是否浏览过关于 SDD 的文章。")
    assert is_no_info_answer("我目前没有看到你提供的【资料】")
    assert is_no_info_answer("我这边看不到你的技术栈信息。")  # 2026-10-02 实测新增变体
    assert is_no_info_answer("我目前没有关于你技术栈的记录。")  # 2026-10-02 实测新增变体


def test_knowledge_answers_are_written_back() -> None:
    assert not is_no_info_answer(
        "根据资料，Jason L. 的技术栈是 Next.js / TypeScript / Python / PostgreSQL / Supabase。"
    )
    assert not is_no_info_answer("SDD 的核心循环是：规格 → 计划 → 任务 → 实现。")
