"""CLI source: statusLine wrapper が dump した cc-context-*.json を読み contract 化。

statusLine の権威 used_percentage はファイルに残らず pipe にしか来ないため、wrapper が
捕捉した dump を読む。schema mismatch は黙って誤値を返さず ContractError を raise（fail-loud）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import core

# statusline-wrapper.sh は session_id を `tr -c 'A-Za-z0-9-' '_' | head -c 64` で
# sanitize して `cc-context-<safe>.json` に dump する。session_id 指定時の照合で
# 同じ sanitize を再現してファイル名を特定する。
# 注: 本実装は Unicode code point 単位、wrapper は UTF-8 byte 単位なので、非 ASCII を
# 含む session_id では sanitize 結果が一致しない (実 session_id は ASCII UUID 前提)。
# 万一ずれても build_contract が dump 内部 session_id と要求値を照合し、誤った dump を
# 黙って返さず error にするため、誤データ返却は起きない (最悪 not-found)。
_SAFE_RE = re.compile(r"[^A-Za-z0-9-]")


def _safe_id(session_id: str) -> str:
    return _SAFE_RE.sub("_", session_id)[:64]


def _dump_dir(dump_dir: str | None = None) -> Path:
    return Path(dump_dir or os.environ.get("CLAUDE_CONTEXT_DUMP_DIR", "/tmp"))


def find_latest_dump(dump_dir: str | None = None) -> Path | None:
    d = _dump_dir(dump_dir)
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


class DumpSource:
    """CLI 用 Source: statusLine dump を session_id で解決し contract 化する。

    core.build_current_usage(DumpSource(), session_id, ...) から使う。鮮度は dump file の
    mtime を基準にする (dump は statusLine 発火ごとに書き換わる)。"""

    session_id_kind = "claude_code_cli"
    stale_label = "dump"
    precise_hint = (
        "正確には対象セッションで一度 assistant ターンを経て dump を更新するか、"
        "session_id を明示してください。"
    )

    def __init__(self, dump_dir: str | None = None) -> None:
        self._dump_dir = dump_dir
        self._requested_sid: str | None = None  # resolve→build_contract 間で照合に使う

    def resolve(self, session_id: str | None) -> tuple[Path, bool]:
        """session_id 指定時はその dump (`cc-context-<safe>.json`) を尊重。
        省略時のみ最新 mtime に fallback (auto_selected=True)。"""
        self._requested_sid = session_id
        if session_id:
            p = _dump_dir(self._dump_dir) / f"cc-context-{_safe_id(session_id)}.json"
            if not p.exists():
                # raw session_id を echo しない (path/PII を渡された場合の露出回避)
                raise FileNotFoundError(
                    "requested session_id not found "
                    "(statusline-wrapper.sh 未設定か、そのセッションの assistant turn 未経過)"
                )
            return p, False
        p = find_latest_dump(self._dump_dir)
        if p is None:
            raise FileNotFoundError(
                "no context dump found (statusline-wrapper.sh 未設定か assistant turn 未経過)"
            )
        return p, True

    def source_file(self, handle: Path) -> str:
        return handle.name  # basename only — 絶対パスは環境固有なので返さない

    def build_contract(self, handle: Path, now_ts: int) -> dict:
        raw = read_dump(handle)
        # sanitize 衝突 ('abc.def' と 'abc_def' は同一ファイル名) や非 ASCII parity ずれで
        # 別セッションの dump に解決されうるため、dump 内部の session_id と要求値を厳密照合する。
        # 一致しなければ「指定 session_id を尊重」契約を黙って破らず error を返す。
        if self._requested_sid and raw.get("session_id") != self._requested_sid:
            return {
                "error": "requested session_id not found (resolved dump belongs to another session)",
                "source_file": handle.name,
            }
        out = dump_to_contract(raw, now_ts)
        if out.get("status") == "incomplete":
            return out  # 初回応答前 / null 値: 鮮度判定せず terminal
        try:
            out["last_event_age_seconds"] = int(now_ts - handle.stat().st_mtime)
        except OSError:
            out["last_event_age_seconds"] = None
        out["last_event_ts"] = None  # dump 自体に event ts は無い (鮮度は file mtime)
        return out
