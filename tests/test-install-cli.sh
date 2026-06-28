#!/usr/bin/env bash
# test-install-cli.sh — exercise scripts/install-cli.sh statusLine merge (config-only).
# Uses CC_INSTALL_SKIP_INSTALL/SKIP_MCP so no venv/pip/claude side effects.
# Requires: bash, jq.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${ROOT}/scripts/install-cli.sh"
WRAPPER="${ROOT}/scripts/statusline-wrapper.sh"
export CC_INSTALL_SKIP_INSTALL=1 CC_INSTALL_SKIP_MCP=1

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }

# A) no settings file -> creates valid JSON whose statusLine points at the wrapper
A="${TMP}/a/settings.json"
CLAUDE_SETTINGS="${A}" bash "${INSTALLER}" >/dev/null || fail "A: installer exited non-zero"
[ "$(jq -r '.statusLine.command' "${A}")" = "${WRAPPER}" ] || fail "A: statusLine.command not set to wrapper"
echo "PASS A: creates valid settings.json with statusLine"

# B) existing keys preserved + statusLine added
B="${TMP}/b/settings.json"; mkdir -p "$(dirname "${B}")"
printf '{"hooks":{"PostToolUse":[1]},"model":"x"}\n' > "${B}"
CLAUDE_SETTINGS="${B}" bash "${INSTALLER}" >/dev/null || fail "B: installer exited non-zero"
jq -e '.hooks.PostToolUse[0]==1 and .model=="x" and (.statusLine.command|length>0)' "${B}" >/dev/null \
    || fail "B: existing keys not preserved or statusLine missing"
ls "${B}.cc-context.bak."* >/dev/null 2>&1 || fail "B: no timestamped backup created"
echo "PASS B: preserves existing keys + writes timestamped backup"

# C) existing statusLine is NOT overwritten
C="${TMP}/c/settings.json"; mkdir -p "$(dirname "${C}")"
printf '{"statusLine":{"type":"command","command":"/my/own"}}\n' > "${C}"
CLAUDE_SETTINGS="${C}" bash "${INSTALLER}" >/dev/null || fail "C: installer exited non-zero"
[ "$(jq -r '.statusLine.command' "${C}")" = "/my/own" ] || fail "C: overwrote an existing statusLine"
echo "PASS C: does not overwrite an existing statusLine"

# D) settings path containing a space -> still produces valid JSON (no breakage/injection)
D="${TMP}/d e/settings.json"; mkdir -p "${TMP}/d e"
CLAUDE_SETTINGS="${D}" bash "${INSTALLER}" >/dev/null || fail "D: installer exited non-zero"
jq -e '.statusLine.type=="command"' "${D}" >/dev/null || fail "D: invalid JSON for spaced settings path"
echo "PASS D: handles a spaced settings path, valid JSON"

echo "ALL PASS: install-cli.sh statusLine merge"
