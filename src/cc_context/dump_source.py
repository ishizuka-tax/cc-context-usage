"""CLI source: statusLine wrapper が dump した cc-context-*.json を読み contract 化。

statusLine の権威 used_percentage はファイルに残らず pipe にしか来ないため、wrapper が
捕捉した dump を読む。schema mismatch は黙って誤値を返さず ContractError を raise（fail-loud）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import core


def find_latest_dump(dump_dir: str | None = None) -> Path | None:
    d = Path(dump_dir or os.environ.get("CLAUDE_CONTEXT_DUMP_DIR", "/tmp"))
    cands = sorted(
        d.glob("cc-context-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return cands[0] if cands else None


def read_dump(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump_to_contract(raw: dict, now_ts: int) -> dict:
    cw = raw.get("context_window")
    if not isinstance(cw, dict):
        raise core.ContractError(
            "dump missing 'context_window' (statusLine schema changed?)"
        )
    if cw.get("used_percentage") is None or cw.get("current_usage") is None:
        return {
            "status": "incomplete",
            "session_id": raw.get("session_id"),
            "session_id_kind": "claude_code_cli",
            "model": (raw.get("model") or {}).get("display_name"),
            "reason": "used_percentage / current_usage が null (初回 API 応答前 or /compact 直後)",
        }
    cu = cw["current_usage"]
    model = (raw.get("model") or {}).get("display_name", "unknown")
    out = core.usage_to_contract(cu, model)
    # statusLine の権威値を優先採用（core 再計算でなく公式値）
    out["usage_percentage"] = cw.get("used_percentage")
    out["context_window_limit"] = cw.get("context_window_size", out["context_window_limit"])
    out["context_window_used"] = cw.get("total_input_tokens", out["context_window_used"])
    out["session_id_kind"] = "claude_code_cli"
    out["session_id"] = raw.get("session_id")
    out["remaining_percentage"] = cw.get("remaining_percentage")
    rl = raw.get("rate_limits") or {}
    out["rate_limits"] = (
        {
            w: core.format_rate_window(
                (rl.get(w) or {}).get("used_percentage"),
                (rl.get(w) or {}).get("resets_at"),
                w,
                now_ts,
            )
            for w in ("five_hour", "seven_day")
        }
        if rl
        else None
    )
    core.validate_contract(out)
    return out
