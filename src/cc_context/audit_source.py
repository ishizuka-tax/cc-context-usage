"""Desktop (Cowork) データソース: host の audit.jsonl を tail-read し usage/rate/meta を返す。

権威ある usage は Claude Desktop が audit.jsonl に永続化するため、host 側から直接読める
(VM 内 read は mount snapshot 問題で不可)。window 整形・contract 計算は core に委譲。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import core

DEFAULT_BASE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    / "Packages"
    / "Claude_pzs8sxrjxfjjc"
    / "LocalCache"
    / "Roaming"
    / "Claude"
    / "local-agent-mode-sessions"
)
BASE_DIR = Path(os.environ.get("COWORK_AUDIT_BASE", str(DEFAULT_BASE)))
TAIL_CHUNK_BYTES = 1024 * 1024

# session_id は path 構築に使うため `local_<uuid>` に限定し traversal を防ぐ。
_SESSION_ID_RE = re.compile(r"^local_[A-Za-z0-9-]+$")


def _scan_sessions() -> list[tuple[float, Path]]:
    found: list[tuple[float, Path]] = []
    if not BASE_DIR.is_dir():
        return found
    for workspace in BASE_DIR.iterdir():
        if not workspace.is_dir():
            continue
        for account in workspace.iterdir():
            if not account.is_dir():
                continue
            for session in account.iterdir():
                if not session.is_dir():
                    continue
                audit = session / "audit.jsonl"
                if audit.exists():
                    try:
                        found.append((audit.stat().st_mtime, session))
                    except OSError:
                        continue
    return found


def resolve_session(session_id: str | None) -> Path:
    """session_id から session ディレクトリを解決。明示 id が `local_<uuid>` 形でなければ
    FileNotFoundError (traversal 防止)。省略時は最新 mtime の session。"""
    sid = session_id or os.environ.get("COWORK_CONTEXT_SESSION_ID")
    if sid:
        if not _SESSION_ID_RE.match(sid):
            raise FileNotFoundError(f"invalid session_id {sid!r} (expected 'local_<uuid>')")
        if not BASE_DIR.is_dir():
            # 絶対パス (username 等) を error に載せない (basename-only privacy 方針)
            raise FileNotFoundError("cowork audit base dir not found (set COWORK_AUDIT_BASE?)")
        for workspace in BASE_DIR.iterdir():
            if not workspace.is_dir():
                continue
            for account in workspace.iterdir():
                if not account.is_dir():
                    continue
                candidate = account / sid
                if (candidate / "audit.jsonl").exists():
                    return candidate
        raise FileNotFoundError(f"session_id {sid!r} not found")
    sessions = _scan_sessions()
    if not sessions:
        raise FileNotFoundError("no cowork audit.jsonl found (no active session?)")
    sessions.sort(reverse=True)
    return sessions[0][1]


def _iter_tail_lines(path: Path, chunk_bytes: int = TAIL_CHUNK_BYTES):
    """ファイルを末尾から逆順に line yield する generator。"""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        position = fh.tell()
        carry = b""
        while position > 0:
            read_size = min(chunk_bytes, position)
            position -= read_size
            fh.seek(position)
            chunk = fh.read(read_size) + carry
            lines = chunk.split(b"\n")
            if position > 0:
                carry = lines[0]
                lines = lines[1:]
            else:
                carry = b""
            for line in reversed(lines):
                if line:
                    yield line.decode("utf-8", errors="replace")


def find_last_event(path: Path, event_type: str) -> dict | None:
    for line in _iter_tail_lines(path):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == event_type:
            return obj
    return None


def find_last_event_for_session(path: Path, event_type: str, session_id: str) -> dict | None:
    """parent (session_id=local_<uuid>) と sub (cliSessionId) の event 混在 audit で、
    parent の値を返したい場合に使う。一致なしは None。"""
    for line in _iter_tail_lines(path):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == event_type and obj.get("session_id") == session_id:
            return obj
    return None


def _iter_events(path: Path, event_type: str):
    """指定 type の event を末尾から (newest-first) 逐次 yield する generator。"""
    for line in _iter_tail_lines(path):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == event_type:
            yield obj


def find_last_n_events(path: Path, event_type: str, n: int) -> list[dict]:
    out: list[dict] = []
    for obj in _iter_events(path, event_type):
        out.append(obj)
        if len(out) >= n:
            break
    return out


def _find_last_rate_limit_by_type(audit_path: Path, rate_limit_type: str) -> dict | None:
    """cowork 実機 schema (1 event = 1 type) の指定 rateLimitType の最新 event。"""
    for line in _iter_tail_lines(audit_path):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "rate_limit_event":
            continue
        info = obj.get("rate_limit_info") or {}
        if info.get("rateLimitType") == rate_limit_type:
            return obj
    return None


# ---------------------------------------------------------------------------
# 高レベル API (desktop adapter が使う)
# ---------------------------------------------------------------------------


def _parse_iso(ts: str | None) -> datetime | None:
    """audit の `_audit_timestamp` (例 '2026-06-28T11:37:28.871Z') を datetime に。
    非 str (None / malformed audit の数値等) や parse 不能は None。"""
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_seconds(ts_iso: str | None) -> int | None:
    """ISO timestamp から現在までの経過秒。解釈不能なら None。"""
    dt = _parse_iso(ts_iso)
    if dt is None:
        return None
    return int(datetime.now(timezone.utc).timestamp() - dt.timestamp())


def latest_assistant_usage(session_dir: Path) -> tuple[dict, str, str | None] | None:
    """parent-filter 優先で最新 assistant の (usage, model, audit_ts) を返す。無ければ None。

    audit_ts は当該 event の `_audit_timestamp`（ISO 文字列 or None）。staleness 判定に使う。"""
    audit = session_dir / "audit.jsonl"
    ev = find_last_event_for_session(audit, "assistant", session_dir.name) or find_last_event(
        audit, "assistant"
    )
    if not ev:
        return None
    msg = ev.get("message", {}) or {}
    return msg.get("usage", {}) or {}, msg.get("model", "unknown"), ev.get("_audit_timestamp")


def latest_rate_limits(session_dir: Path) -> dict | None:
    """cowork 実機 schema (rate_limit_info) から {five_hour, seven_day} を core 整形で返す。"""
    audit = session_dir / "audit.jsonl"
    now = int(time.time())
    out: dict[str, Any] = {}
    for win in ("five_hour", "seven_day"):
        e = _find_last_rate_limit_by_type(audit, win)
        info = (e or {}).get("rate_limit_info") or {}
        util = info.get("utilization")
        pct = round(float(util) * 100, 1) if util is not None else None
        w = core.format_rate_window(pct, info.get("resetsAt"), win, now)
        if w is not None:
            w["status"] = info.get("status")
        out[win] = w
    return out if any(out.values()) else None


def result_history(session_dir: Path, n: int) -> list[dict]:
    """直近 N 件の「実測のある turn 終了時点」context window size 推移 (newest-first)。

    cowork の audit には usage payload を持たない result event (iterations も top-level
    usage tokens も空 → context_window_size 0) も書かれる。これは「窓が 0 に落ちた」かの
    ように見える spike 検出のノイズなので **除外**し、実測のある行 (context_window_size > 0)
    のみを最大 N 件返す。そのため N 件揃えるのに N 件以上の result event を走査することがある。
    is_error の result event でも実測がある行 (失敗 / overflow turn の spike) は残し、
    返り値の `is_error` flag で示す (消費側がさらに絞れる)。"""
    if n <= 0:
        return []
    audit = session_dir / "audit.jsonl"
    history = []
    for ev in _iter_events(audit, "result"):
        usage = ev.get("usage", {}) or {}
        iterations = usage.get("iterations", []) or []
        src = iterations[-1] if iterations else usage
        input_t = int(src.get("input_tokens", 0) or 0)
        cache_c = int(src.get("cache_creation_input_tokens", 0) or 0)
        cache_r = int(src.get("cache_read_input_tokens", 0) or 0)
        output_t = int(src.get("output_tokens", 0) or 0)
        window = input_t + cache_c + cache_r
        # 実測のない (window 0) 行は「窓が 0」と誤読されるノイズなのでスキップ
        if window <= 0:
            continue
        history.append(
            {
                "ts": ev.get("_audit_timestamp"),
                "context_window_size": window,
                "input_tokens": input_t,
                "cache_creation_input_tokens": cache_c,
                "cache_read_input_tokens": cache_r,
                "output_tokens": output_t,
                "source": "iterations[-1]" if iterations else "usage (fallback)",
                "is_error": ev.get("is_error"),
            }
        )
        if len(history) >= n:
            break
    return history


def session_meta(session_dir: Path) -> dict:
    """local_<sessionId>.json から metadata を whitelist で返す。
    **PII / 環境固有値 (emailAddress/cwd/processName/vmProcessName/accountName/spaceId) は返さない**。"""
    sid = session_dir.name
    local_json = session_dir.parent / f"{sid}.json"
    if not local_json.exists():
        # 絶対パスを error に載せない (basename-only privacy 方針)
        return {"error": f"session meta file not found for {sid}", "session_id": sid}
    try:
        with open(local_json, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"failed to read session meta for {sid}: {type(e).__name__}", "session_id": sid}

    def _ts(ms: Any) -> str | None:
        if not isinstance(ms, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    return {
        "session_id": data.get("sessionId"),
        "model": data.get("model"),
        "title": data.get("title"),
        "created_at": _ts(data.get("createdAt")),
        "last_activity_at": _ts(data.get("lastActivityAt")),
        "host_loop_mode": data.get("hostLoopMode"),
        "memory_enabled": data.get("memoryEnabled"),
        "skills_enabled": data.get("skillsEnabled"),
        "plugins_enabled": data.get("pluginsEnabled"),
        "is_archived": data.get("isArchived"),
        "is_starred": data.get("isStarred"),
        "system_prompt_length": len(data.get("systemPrompt") or ""),
        "source_file": local_json.name,  # basename only — 絶対パスは環境固有値なので返さない (docstring の whitelist 方針と整合)
    }


class AuditSource:
    """Desktop (Cowork) 用 Source: host の audit.jsonl を session_id で解決し contract 化する。

    core.build_current_usage(AuditSource(), session_id, ...) から使う。鮮度は当該 assistant
    event の `_audit_timestamp` を基準にする。raw 取得は module 関数 (resolve_session 等) に
    委譲し、staleness 判定・status 語彙は core に統一。"""

    session_id_kind = "cowork_local"
    stale_label = "audit"
    precise_hint = "正確には session_id（作業ディレクトリの local_<uuid>）を渡してください。"

    def resolve(self, session_id: str | None) -> tuple[Path, bool]:
        # 明示 session_id も COWORK_CONTEXT_SESSION_ID env も無い時だけ「自動選択」
        auto_selected = not session_id and not os.environ.get("COWORK_CONTEXT_SESSION_ID")
        return resolve_session(session_id), auto_selected  # 不在は FileNotFoundError

    def source_file(self, handle: Path) -> str:
        return "audit.jsonl"  # basename only — source は session_id で特定可

    def build_contract(self, session_dir: Path, now_ts: int) -> dict:
        got = latest_assistant_usage(session_dir)
        if got is None:
            return {"error": "No assistant event", "session_id": session_dir.name}
        usage, model, audit_ts = got
        out = core.usage_to_contract(usage, model)
        out["session_id_kind"] = self.session_id_kind
        out["session_id"] = session_dir.name
        out["source_file"] = "audit.jsonl"
        out["rate_limits"] = latest_rate_limits(session_dir)
        out["last_event_ts"] = audit_ts if isinstance(audit_ts, str) else None
        out["last_event_age_seconds"] = age_seconds(audit_ts)
        return out
