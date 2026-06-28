"""Claude Code CLI MCP server: statusLine wrapper の dump から context 使用率を返す。

前提: statusLine.command に同梱 scripts/statusline-wrapper.sh を設定し dump を生成すること。
`context_window_used` の意味は Desktop 版と同一（input-only 実績、billing/rate limit/`/context` と別）。
"""
from __future__ import annotations

import time

from mcp.server.fastmcp import FastMCP

from . import core, dump_source

mcp = FastMCP("cc-context")


@mcp.tool()
def get_current_context_usage(session_id: str | None = None) -> dict:
    """現在の context window 使用量 + rate_limits を返す（statusLine dump 由来）。

    `usage_percentage` は Claude Code 公式の事前計算値。`context_window_used` は input-only
    実績で、billing / ITPM rate limit / `/context`（次ターン推定）とは別概念。

    出力 shape・session_id の扱い・staleness guard は Desktop 版と統一（共通
    `core.build_current_usage`）。`session_id` を渡すとその session の dump を尊重し、
    省略時のみ最新 dump に自動 fallback する。鮮度は dump file の mtime 基準で、古ければ
    `status:"stale"`。dump がまだ無い / 初回応答前は `status:"incomplete"`、dump の schema
    が変わって必須 field を欠く場合は黙って誤値を返さず error を返す（fail-loud）。
    """
    return core.build_current_usage(
        dump_source.DumpSource(), session_id, now_ts=int(time.time())
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
