#!/usr/bin/env bash
# test-uninstall-cli.sh — exercise scripts/uninstall-cli.sh statusLine revert.
# Skips MCP unregister + venv removal so there are no side effects. Requires bash, jq.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UNINSTALL="${ROOT}/scripts/uninstall-cli.sh"
WRAPPER="${ROOT}/scripts/statusline-wrapper.sh"
export CC_INSTALL_SKIP_MCP=1 CC_INSTALL_SKIP_INSTALL=1

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }

# A) statusLine points at THIS wrapper -> removed, other keys preserved
A="${TMP}/a.json"
jq -n --arg c "${WRAPPER}" '{statusLine:{type:"command",command:$c}, model:"x"}' > "${A}"
CLAUDE_SETTINGS="${A}" bash "${UNINSTALL}" >/dev/null || fail "A: uninstall exited non-zero"
jq -e 'has("statusLine") | not' "${A}" >/dev/null || fail "A: statusLine not removed"
jq -e '.model == "x"' "${A}" >/dev/null || fail "A: other keys not preserved"
ls "${A}.cc-context.bak."* >/dev/null 2>&1 || fail "A: no backup created"
echo "PASS A: removes our statusLine, preserves other keys, backs up"

# B) statusLine points at SOMETHING ELSE -> left as-is
B="${TMP}/b.json"
printf '{"statusLine":{"type":"command","command":"/someone/else"}}\n' > "${B}"
CLAUDE_SETTINGS="${B}" bash "${UNINSTALL}" >/dev/null || fail "B: uninstall exited non-zero"
[ "$(jq -r '.statusLine.command' "${B}")" = "/someone/else" ] || fail "B: removed a foreign statusLine"
echo "PASS B: leaves a non-ours statusLine untouched"

echo "ALL PASS: uninstall-cli.sh statusLine revert"
