"""Desktop (Cowork) MCP server: host の audit.jsonl を読み context 使用率を返す。

Install: pip install . → claude_desktop_config.json の mcpServers.cc-context に
command=<venv python> args=["-m","cc_context.desktop"]（または console script cc-context-desktop）。
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from . import audit_source, core

mcp = FastMCP("cc-context")

# 選んだ audit がこの秒数より古ければ status="stale"（誤値の沈黙を防ぐ）。env で調整可。
DEFAULT_STALE_SECONDS = 600


@mcp.tool()
def get_current_context_usage(session_id: str | None = None) -> dict:
    """現在の context window 使用量 + rate_limits を返す。

    `context_window_used` = input + cache_creation + cache_read（input-only 基準、
    直前 API request の実績）。**billing とは別**（cache read は単価低）、**ITPM rate
    limit とも別**（cache read はカウント外が多い）、**`/context` とも別**（あちらは
    次ターン投入予定の推定、本値は実績）。
    `rate_limits.{five_hour,seven_day}` は最新 rate_limit_event から抽出（未発火なら null）。

    **Desktop の精度の注意**: MCP サーバーは現在の会話 ID を受け取れない（共有プロセス）。
    `session_id` 省略時は **最新 mtime の audit を自動選択** するため、新セッションの初回や
    複数 cowork 会話の並行時に **別セッションを掴む / 1 ターン遅れる** ことがある。
    正確に測るには **`session_id` を渡す**（cowork では作業ディレクトリ末尾の `local_<uuid>`）。
    返り値の `status`（"ok"/"stale"/"unknown"）と `last_event_age_seconds` で鮮度を判断できる。
    手動確認だけなら `/context` でもよい。
    """
    # 明示 session_id も COWORK_CONTEXT_SESSION_ID env も無い時だけ「自動選択」(stale note 用)
    auto_selected = not session_id and not os.environ.get("COWORK_CONTEXT_SESSION_ID")
    try:
        sdir = audit_source.resolve_session(session_id)
    except FileNotFoundError as e:
        return {"error": str(e)}
    got = audit_source.latest_assistant_usage(sdir)
    if got is None:
        return {"error": "No assistant event", "session_id": sdir.name}
    usage, model, audit_ts = got
    out = core.usage_to_contract(usage, model)
    out["session_id_kind"] = "cowork_local"
    out["session_id"] = sdir.name
    out["source_file"] = "audit.jsonl"  # basename only — 絶対パスは環境固有 (user名/端末構成) なので返さない。source は session_id で特定可
    out["rate_limits"] = audit_source.latest_rate_limits(sdir)
    # --- staleness guard: 黙って別セッション/古い値を返さない ---
    age = audit_source.age_seconds(audit_ts)
    out["last_event_ts"] = audit_ts if isinstance(audit_ts, str) else None
    out["last_event_age_seconds"] = age
    try:
        threshold = int(os.environ.get("CC_CONTEXT_STALE_SECONDS", DEFAULT_STALE_SECONDS))
    except ValueError:
        threshold = DEFAULT_STALE_SECONDS
    if age is None:
        out["status"] = "unknown"
        out["status_note"] = "audit timestamp を解釈できず、鮮度を判定できません。"
    elif age < 0:
        out["status"] = "unknown"
        out["status_note"] = "audit timestamp が未来（clock skew / 破損の可能性）で鮮度を判定できません。"
    elif age > threshold:
        out["status"] = "stale"
        out["status_note"] = (
            f"選択した audit は {age}s 前のもの（しきい値 {threshold}s 超）。"
            + (
                "自動選択のため、別（過去の）セッションを掴んでいるか、現ターンが未 flush の"
                "可能性があります。正確には session_id（作業ディレクトリの local_<uuid>）を渡してください。"
                if auto_selected
                else "指定セッションの値ですが、最新ターンがまだ flush されていない可能性があります。"
            )
        )
    else:
        out["status"] = "ok"
    core.validate_contract(out)
    return out


@mcp.tool()
def get_context_history(session_id: str | None = None, n: int = 10) -> dict:
    """直近 N ターンの context window size 推移（spike 検出用）。各値は result event の
    iterations[-1] 由来（turn 終了時点、1M を超えない）。"""
    if n <= 0:
        return {"error": "n must be positive"}
    try:
        sdir = audit_source.resolve_session(session_id)
    except FileNotFoundError as e:
        return {"error": str(e)}
    return {"session_id": sdir.name, "history": audit_source.result_history(sdir, n)}


@mcp.tool()
def get_session_meta(session_id: str | None = None) -> dict:
    """session metadata（model/title/created_at 等）を返す。**PII / 環境固有値
    (emailAddress/cwd/processName/vmProcessName/accountName/spaceId) は返さない**（whitelist）。
    注: sub-agent (Task) 実行中は parent の値が静止して見える。"""
    try:
        sdir = audit_source.resolve_session(session_id)
    except FileNotFoundError as e:
        return {"error": str(e)}
    return audit_source.session_meta(sdir)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
