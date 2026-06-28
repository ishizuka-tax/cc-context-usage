import pytest

from cc_context import core


def test_normalize_model_strips_suffix():
    assert core.normalize_model("claude-opus-4-8[1m]") == "claude-opus-4-8"


def test_context_limit_known_and_fallback():
    assert core.context_limit_for("claude-opus-4-8") == 1000000
    assert core.context_limit_for("totally-unknown") == 1000000  # _fallback


def test_usage_to_contract_sums_input_only():
    c = core.usage_to_contract(
        {
            "input_tokens": 2,
            "cache_creation_input_tokens": 838,
            "cache_read_input_tokens": 56544,
            "output_tokens": 41,
        },
        "claude-opus-4-8",
    )
    assert c["context_window_used"] == 2 + 838 + 56544  # output 除外
    assert c["context_window_limit"] == 1000000
    assert c["usage_percentage"] == round((2 + 838 + 56544) / 1000000 * 100, 2)
    assert c["breakdown"]["output_tokens"] == 41
    assert c["model_normalized"] == "claude-opus-4-8"


def test_format_rate_window_human():
    w = core.format_rate_window(99, 1000 + 4228, "five_hour", 1000)
    assert w["resets_in_seconds"] == 4228
    assert w["resets_in_human"] == "1h10m"
    assert (
        core.format_rate_window(1, 500, "five_hour", 1000)["resets_in_human"]
        == "expired"
    )
    d = core.format_rate_window(50, 1000 + 100000, "seven_day", 1000)
    assert "d" in d["resets_in_human"] and d["resets_in_human"].endswith("h")


def test_validate_contract_raises_on_missing():
    with pytest.raises(core.ContractError):
        core.validate_contract({"usage_percentage": 5})  # 必須 key 欠落
