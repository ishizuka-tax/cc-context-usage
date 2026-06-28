#!/usr/bin/env bash
# scripts/statusline-wrapper.sh
#
# Claude Code statusLine wrapper:
#   1. stdin の rich JSON (context_window / cost / rate_limits 等を含む) を
#      /tmp/cc-context-<session_id>.json に atomic write で dump
#      → このスキルの CLI recipe (references/cli.md) や PostToolUse hook が後続で読む
#   2. 同じ JSON を表示用コマンド (既定 ccstatusline) に pass-through し、stdout は
#      その表示文字列 → 既存の statusLine 表示挙動を維持
#
# 設計根拠: Claude Code 公式 docs (https://code.claude.com/docs/en/statusline) によると
# statusLine command の stdin には context_window.{context_window_size, used_percentage,
# current_usage, ...} が含まれる。本 wrapper で「表示 + dump」を同時に行い、後続の
# 利用側 (このスキルの CLI recipe 等) は dump file から公式の事前計算値を直接読める。
#
# ----------------------------------------------------------------------------
# セットアップ:
#   1. 本スクリプトを実行可能にする:  chmod +x statusline-wrapper.sh
#   2. Claude Code の settings.json (~/.claude/settings.json) に statusLine を登録:
#
#        "statusLine": {
#          "type": "command",
#          "command": "/absolute/path/to/statusline-wrapper.sh"
#        }
#
#   3. (任意) 表示部に ccstatusline を使う場合は別途インストール。未インストールでも
#      dump-only モードで動作する (表示は最小限の fallback になる)。
# ----------------------------------------------------------------------------
#
# 環境変数 (override):
#   CLAUDE_CONTEXT_DUMP_DIR    dump 出力先ディレクトリ (default: /tmp)
#   CLAUDE_CONTEXT_WRAPPED_CMD 表示用コマンド (default: ccstatusline。
#                              `cat` や `true` を指定すれば表示なしの no-op にできる)
#                              注: eval せず空白区切りで argv 分割するため「コマンド名 + 単純な引数」
#                              のみ対応。パスに空白を含む / シェル quoting が要る場合は wrapper script
#                              にまとめて、そのパスを指定すること。

set -uo pipefail

INPUT="$(cat)"

DUMP_DIR="${CLAUDE_CONTEXT_DUMP_DIR:-/tmp}"
WRAPPED_CMD="${CLAUDE_CONTEXT_WRAPPED_CMD:-ccstatusline}"

# session_id 取得 (失敗時 'default')
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // "default"' 2>/dev/null)"
SESSION_ID="${SESSION_ID:-default}"
# session_id をファイル名に使うため、不正文字を sanitize (英数 + '-' のみ通す)
# printf '%s' で末尾改行を含めない (echo だと改行が '_' に変換され session_id 末尾に '_' が付く)
SAFE_ID="$(printf '%s' "$SESSION_ID" | tr -c 'A-Za-z0-9-' '_' | head -c 64)"
DUMP_PATH="${DUMP_DIR}/cc-context-${SAFE_ID}.json"

# atomic write: 同 directory 内の mktemp → mv (rename) で書き換え途中の読みを防ぐ
TMP_PATH="$(mktemp "${DUMP_PATH}.XXXXXX" 2>/dev/null)"
if [[ -n "$TMP_PATH" ]]; then
    printf '%s\n' "$INPUT" > "$TMP_PATH"
    mv -f "$TMP_PATH" "$DUMP_PATH" 2>/dev/null || rm -f "$TMP_PATH" 2>/dev/null
fi

# pass-through: 元の statusLine 表示機能を維持。
# eval は使わず WRAPPED_CMD を argv に word-split して実行する (任意シェル文字列を
# eval する injection リスクを避ける。`ccstatusline --hook` のような cmd+args は維持)。
read -r -a WRAPPED_ARGV <<< "$WRAPPED_CMD"
if [[ ${#WRAPPED_ARGV[@]} -gt 0 ]] && command -v "${WRAPPED_ARGV[0]}" >/dev/null 2>&1; then
    printf '%s' "$INPUT" | "${WRAPPED_ARGV[@]}"
else
    # wrapped command 不在: 最低限の表示で fallback
    echo "[statusline-wrapper: '${WRAPPED_ARGV[0]:-}' not found, dump-only mode]"
fi
