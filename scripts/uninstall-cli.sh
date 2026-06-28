#!/usr/bin/env bash
# uninstall-cli.sh — reverse scripts/install-cli.sh.
#
#   1. unregister the cc-context MCP server (user scope)
#   2. remove statusLine ONLY if it still points at this repo's wrapper (timestamped backup)
#   3. remove the venv
#
# Usage:
#   scripts/uninstall-cli.sh [VENV_DIR]      # default VENV_DIR = <repo>/.venv
# Env:
#   CLAUDE_SETTINGS        path to settings.json (default: ~/.claude/settings.json)
#   CC_INSTALL_SKIP_MCP=1       skip the MCP unregister step
#   CC_INSTALL_SKIP_INSTALL=1   skip removing the venv
# Requires: jq (for the statusLine revert) ; `claude` CLI optional.

set -uo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${1:-${REPO}/.venv}"
SETTINGS="${CLAUDE_SETTINGS:-${HOME}/.claude/settings.json}"
WRAPPER="${REPO}/scripts/statusline-wrapper.sh"

echo "==> Unregistering the MCP server 'cc-context' (user scope)"
if [ "${CC_INSTALL_SKIP_MCP:-}" != "1" ] && command -v claude >/dev/null 2>&1; then
    if claude mcp remove -s user cc-context 2>/dev/null; then
        echo "    removed 'cc-context' from user scope"
    else
        echo "    'cc-context' not in user scope (already absent, or another scope)"
        echo "    if it was added at local scope: run 'claude mcp remove -s local cc-context'"
        echo "    from the directory where it was installed."
    fi
fi

echo "==> Reverting statusLine (only if it points at this wrapper)"
if command -v jq >/dev/null 2>&1 && [ -f "${SETTINGS}" ]; then
    cur="$(jq -r '.statusLine.command // empty' "${SETTINGS}")"
    if [ "${cur}" = "${WRAPPER}" ]; then
        cp -- "${SETTINGS}" "${SETTINGS}.cc-context.bak.$(date +%Y%m%d%H%M%S%N)"
        tmp="$(mktemp -- "${SETTINGS}.XXXXXX")"
        jq 'del(.statusLine)' "${SETTINGS}" > "${tmp}"
        mv -- "${tmp}" "${SETTINGS}"
        echo "    removed statusLine (it pointed at this wrapper); backup kept"
    else
        echo "    statusLine is not this wrapper; leaving it as-is: ${cur:-<none>}"
    fi
fi

echo "==> Removing the venv"
if [ "${CC_INSTALL_SKIP_INSTALL:-}" != "1" ] && [ -d "${VENV}" ]; then
    rm -rf -- "${VENV}"
    echo "    removed ${VENV}"
fi

echo
echo "Done. (Backups *.cc-context.bak.* are kept; delete them manually if unneeded.)"
echo "Open a new Claude Code session for the unregistration to take effect."
