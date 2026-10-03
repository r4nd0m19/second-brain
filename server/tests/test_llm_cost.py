"""usage 计费估算单测（R22 计费口径修正，2026-10-03）。

口径：deepseek-flash 官方分档价（空闲基准：命中 0.02 / 未命中 1.0 / 输出 4.0 元每百万），
高峰（北京时间周一至五 9-12/14-18）×2；缓存命中与未命中分开计价。
"""

from app.chat import llm


def test_off_peak_split_cache_hit(monkeypatch):
    monkeypatch.setattr(llm, "_is_peak_now", lambda: False)
    usage = {
        "prompt_tokens": 1_000_000,
        "prompt_cache_hit_tokens": 800_000,
        "completion_tokens": 1_000_000,
    }
    # 命中 0.8M×0.02 + 未命中 0.2M×1.0 + 输出 1M×4.0 = 0.016 + 0.2 + 4.0
    assert abs(llm.estimate_cost_cny(usage) - 4.216) < 1e-9


def test_peak_doubles_price(monkeypatch):
    monkeypatch.setattr(llm, "_is_peak_now", lambda: True)
    usage = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0, "completion_tokens": 0}
    # 未命中 1M×1.0×2（高峰）= 2.0
    assert abs(llm.estimate_cost_cny(usage) - 2.0) < 1e-9


def test_missing_cache_field_treated_as_miss(monkeypatch):
    monkeypatch.setattr(llm, "_is_peak_now", lambda: False)
    usage = {"prompt_tokens": 500_000, "completion_tokens": 250_000}
    # 0.5M×1.0 + 0.25M×4.0 = 1.5
    assert abs(llm.estimate_cost_cny(usage) - 1.5) < 1e-9


def test_hit_exceeds_prompt_clamped(monkeypatch):
    monkeypatch.setattr(llm, "_is_peak_now", lambda: False)
    # 异常数据（命中数 > 总数）不应产生负的未命中计费
    usage = {"prompt_tokens": 100, "prompt_cache_hit_tokens": 500, "completion_tokens": 0}
    assert abs(llm.estimate_cost_cny(usage) - 500 / 1_000_000 * 0.02) < 1e-12


def test_anthropic_style_usage_mapping(monkeypatch):
    """T086：Anthropic 风格 usage（input/cache_read/output，input 不含缓存）→ 同分档定价。"""
    monkeypatch.setattr(llm, "_is_peak_now", lambda: False)
    usage = {
        "input_tokens": 500_000,
        "cache_read_input_tokens": 300_000,
        "cache_creation_input_tokens": 0,
        "output_tokens": 250_000,
    }
    # 命中 0.3M×0.02 + 未命中 0.5M×1.0 + 输出 0.25M×4.0 = 0.006 + 0.5 + 1.0
    assert abs(llm.estimate_cost_cny_anthropic(usage) - 1.506) < 1e-9
