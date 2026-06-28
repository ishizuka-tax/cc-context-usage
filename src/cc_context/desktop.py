"""Desktop (Cowork) MCP server: host の audit.jsonl を読み context 使用率を返す。

Install: pip install . → claude_desktop_config.json の mcpServers.cc-context に
command=<venv python> args=["-m","cc_context.desktop"]（または console script cc-context-desktop）。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import audit_source, core

mcp = FastMCP("cc-context")


@mcp.tool()
def get_current_context_usage(session_id: str | None = None) -> dict:
    """現在の context window 使用量 + rate_limits を返す。

    `context_window_used` = input + cache_creation + cache_read（input-only 基準、
    直前 API request の実績）。**billing とは別**（cache read は単価低）、**ITPM rate
    limit とも別**（cache read はカウント外が多い）、**`/context` とも別**（あちらは
    次ターン投入予定の推定、本値は実績）。session_id 省略時は最新 audit を自動選択。
    `rate_limits.{five_hour,seven_day}` は最新 rate_limit_event から抽出（未発火なら null）。
    """
    try:
        sdir = audit_source.resolve_session(session_id)
    except FileNotFoundError as e:
        return {"error": str(e)}
    got = audit_source.latest_assistant_usage(sdir)
    if got is None:
        return {"error": "No assistant event", "session_id": sdir.name}
    usage, model = got
    out = core.usage_to_contract(usage, model)
    out["session_id_kind"] = "cowork_local"
    out["session_id"] = sdir.name
    out["source_file"] = "audit.jsonl"  # basename only — 絶対パスは環境固有 (user名/端末構成) なので返さない。source は session_id で特定可
    out["rate_limits"] = audit_source.latest_rate_limits(sdir)
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
