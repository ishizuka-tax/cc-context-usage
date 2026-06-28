"""環境非依存の共有コア: 正規化 / token 上限 / contract 計算 / rate_limits 整形 / contract 検証。

context_window_used = input + cache_creation + cache_read（input-only 基準）。
billing（cache read は単価低）/ rate limit（cache read はカウント外が多い）とは別概念。
/context（次ターン投入予定の推定）とも別で、本値は直前 API request の実績。
"""
from __future__ import annotations

import json
import os
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


# ---------------------------------------------------------------------------
# 統一層: staleness 判定 (第1層=共有コード) + 共通オーケストレータ
#
# CLI (dump) と Desktop (audit.jsonl) はデータソースが違うため raw 取得コードは別
# (Source 実装に隔離) だが、「session_id でソース解決 → 最新 usage を contract 化 →
# 鮮度で status 付与 → validate」という手続きと status 語彙はここで 1 本に統一する。
# ---------------------------------------------------------------------------

DEFAULT_STALE_SECONDS = 600


def stale_threshold() -> int:
    """status=stale と判定する経過秒のしきい値。env CC_CONTEXT_STALE_SECONDS で調整、
    不正値は既定 600 に fallback。CLI/Desktop 両方で同じ env が効く。"""
    try:
        return int(os.environ.get("CC_CONTEXT_STALE_SECONDS", DEFAULT_STALE_SECONDS))
    except ValueError:
        return DEFAULT_STALE_SECONDS


def attach_status(
    out: dict,
    *,
    auto_selected: bool,
    threshold: int,
    stale_label: str = "source",
    precise_hint: str = "",
) -> None:
    """`out["last_event_age_seconds"]` を基に status (ok/stale/unknown) と status_note を付与。

    鮮度の決め方 (age の出し方) はソース依存で Source が `last_event_age_seconds` に
    入れておく。本関数は **判定ロジックと語彙だけ** を担い、CLI/Desktop で挙動を揃える。
    `stale_label` (例 'dump'/'audit') と `precise_hint` (正確に測る方法の案内) のみ
    ソース固有の文言として受ける。"""
    age = out.get("last_event_age_seconds")
    if age is None:
        out["status"] = "unknown"
        out["status_note"] = f"{stale_label} timestamp を解釈できず、鮮度を判定できません。"
    elif age < 0:
        out["status"] = "unknown"
        out["status_note"] = (
            f"{stale_label} timestamp が未来（clock skew / 破損の可能性）で鮮度を判定できません。"
        )
    elif age > threshold:
        out["status"] = "stale"
        head = f"選択した {stale_label} は {age}s 前のもの（しきい値 {threshold}s 超）。"
        if auto_selected:
            out["status_note"] = (
                head
                + "自動選択のため、別（過去の）セッションを掴んでいるか、現ターンが未 flush の"
                + f"可能性があります。{precise_hint}"
            )
        else:
            out["status_note"] = (
                head + "指定セッションの値ですが、最新ターンがまだ flush されていない可能性があります。"
            )
    else:
        out["status"] = "ok"


def build_current_usage(source, session_id: str | None, *, now_ts: int) -> dict:
    """全 adapter 共通の手続き: resolve → build_contract → (terminal は返す) →
    attach_status → validate。

    `source` は以下を満たすオブジェクト (CLI=DumpSource / Desktop=AuditSource):
      - 属性 session_id_kind / stale_label / precise_hint
      - resolve(session_id) -> (handle, auto_selected): ソース不在は FileNotFoundError
      - build_contract(handle, now_ts) -> dict: 完全な contract (last_event_age_seconds 含む、
        status は未設定)。terminal な場合は {"error": ...} か {"status": "incomplete", ...}。
        必須 field 欠落は core.ContractError を raise (fail-loud)。
      - source_file(handle) -> str: error 報告用 (basename)
    """
    try:
        handle, auto_selected = source.resolve(session_id)
    except FileNotFoundError as e:
        return {"error": str(e)}
    try:
        out = source.build_contract(handle, now_ts)
    except ContractError as e:
        return {"error": f"source schema mismatch: {e}", "source_file": source.source_file(handle)}
    # terminal (取得不能 / 初回応答前) は status を被せず、そのまま返す
    if "error" in out or out.get("status") == "incomplete":
        return out
    attach_status(
        out,
        auto_selected=auto_selected,
        threshold=stale_threshold(),
        stale_label=source.stale_label,
        precise_hint=source.precise_hint,
    )
    validate_contract(out)
    return out
