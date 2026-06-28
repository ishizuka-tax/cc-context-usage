"""環境非依存の共有コア: 正規化 / token 上限 / contract 計算 / rate_limits 整形 / contract 検証。

context_window_used = input + cache_creation + cache_read（input-only 基準）。
billing（cache read は単価低）/ rate limit（cache read はカウント外が多い）とは別概念。
/context（次ターン投入予定の推定）とも別で、本値は直前 API request の実績。
"""
from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

_LIMITS_CACHE: dict[str, Any] | None = None
_MODEL_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")


class ContractError(Exception):
    """normalized contract の必須 field 欠落（schema mismatch）。"""


def _limits() -> dict[str, Any]:
    """limits.json をパッケージ data として読む（importlib.resources）。

    非 editable install (pip install .) でも site-packages 内の package data を
    確実に解決するため、__file__ 相対パスではなく importlib.resources を使う。
    """
    global _LIMITS_CACHE
    if _LIMITS_CACHE is None:
        with resources.files("cc_context").joinpath("limits.json").open(
            encoding="utf-8"
        ) as fh:
            _LIMITS_CACHE = json.load(fh)
    return _LIMITS_CACHE


def normalize_model(model: str) -> str:
    return _MODEL_SUFFIX_RE.sub("", model or "").strip()


def context_limit_for(model: str) -> int:
    cfg = _limits()
    return cfg["models"].get(normalize_model(model), cfg["_fallback"])


def usage_to_contract(usage: dict, model: str) -> dict:
    input_t = int(usage.get("input_tokens", 0) or 0)
    cache_c = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_r = int(usage.get("cache_read_input_tokens", 0) or 0)
    output_t = int(usage.get("output_tokens", 0) or 0)
    used = input_t + cache_c + cache_r
    limit = context_limit_for(model)
    pct = round(used / limit * 100, 2) if limit > 0 else 0.0
    return {
        "context_window_used": used,
        "context_window_limit": limit,
        "usage_percentage": pct,
        "model": model,
        "model_normalized": normalize_model(model),
        "breakdown": {
            "input_tokens": input_t,
            "cache_creation_input_tokens": cache_c,
            "cache_read_input_tokens": cache_r,
            "output_tokens": output_t,
        },
    }


def _fmt_hm(s: int) -> str:
    return "expired" if s <= 0 else f"{s // 3600}h{(s % 3600) // 60}m"


def _fmt_dh(s: int) -> str:
    return "expired" if s <= 0 else f"{s // 86400}d{(s % 86400) // 3600}h"


def format_rate_window(used_percentage, resets_at, window: str, now_ts: int) -> dict | None:
    if resets_at is None:
        return None
    try:
        resets_at_int = int(resets_at)
    except (TypeError, ValueError):
        return None
    resets_in = resets_at_int - now_ts
    fmt = _fmt_hm if window == "five_hour" else _fmt_dh
    return {
        "used_percentage": used_percentage,
        "resets_at": resets_at_int,
        "resets_in_seconds": resets_in,
        "resets_in_human": fmt(resets_in),
    }


REQUIRED_CONTRACT_KEYS = frozenset(
    {"context_window_used", "context_window_limit", "usage_percentage", "model", "breakdown"}
)


def validate_contract(d: dict) -> None:
    missing = REQUIRED_CONTRACT_KEYS - set(d)
    if missing:
        raise ContractError(f"contract missing keys: {sorted(missing)}")
