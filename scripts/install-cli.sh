#!/usr/bin/env bash
# install-cli.sh — set up cc-context-usage for the Claude Code CLI.
#
#   1. create a venv and install this package          (skip with CC_INSTALL_SKIP_INSTALL=1)
#   2. register the MCP server `cc-context`             (skip with CC_INSTALL_SKIP_MCP=1; idempotent)
#   3. point statusLine at the bundled wrapper so the dump is produced
#      (timestamped backup; never overwrites an existing statusLine — prints relay guidance)
#
# Usage:
#   scripts/install-cli.sh [VENV_DIR]        # default VENV_DIR = <repo>/.venv
# Env:
#   CLAUDE_SETTINGS        path to settings.json (default: ~/.claude/settings.json)
#   CC_INSTALL_SKIP_INSTALL=1     skip venv + pip (e.g. for config-only re-run / tests)
#   CC_INSTALL_SKIP_MCP=1         skip the `claude mcp add` step
#   CC_INSTALL_SKIP_STATUSLINE=1  skip statusLine config (e.g. you wire statusLine yourself)
# Requires: python3 ; jq (for the statusLine merge) ; `claude` CLI optional.
# Note: if settings.json doesn't parse as JSON, the statusLine step is skipped gracefully
#       (it does not abort the install — the MCP server is still registered).

set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${1:-${REPO}/.venv}"
SETTINGS="${CLAUDE_SETTINGS:-${HOME}/.claude/settings.json}"
WRAPPER="${REPO}/scripts/statusline-wrapper.sh"
PYBIN="${VENV}/bin/python"

if [ "${CC_INSTALL_SKIP_INSTALL:-}" != "1" ]; then
    echo "==> Creating venv at ${VENV} and installing the package"
    python3 -m venv "${VENV}"
    "${VENV}/bin/pip" install --quiet --upgrade pip
    "${VENV}/bin/pip" install "${REPO}"
fi

if [ "${CC_INSTALL_SKIP_MCP:-}" != "1" ]; then
    # --scope user so the tool is available in every session regardless of cwd.
    # (the default scope is "local", bound to the cwd at install time — which makes
    #  the tool invisible in sessions started from a different directory.)
    echo "==> Registering the MCP server 'cc-context' (user scope)"
    if ! command -v claude >/dev/null 2>&1; then
        echo "    'claude' not found on PATH. Register it yourself:"
        echo "      claude mcp add --scope user cc-context -- \"${PYBIN}\" -m cc_context.cli"
    elif claude mcp get cc-context >/dev/null 2>&1; then
        echo "    'cc-context' is already registered; leaving it as-is"
        echo "    (to update: claude mcp remove -s user cc-context, then re-run)."
    elif claude mcp add --scope user cc-context -- "${PYBIN}" -m cc_context.cli; then
        echo "    registered 'cc-context' (user scope)"
    else
        # a registration failure must not abort the statusLine step below (set -e)
        echo "    WARN: 'claude mcp add' failed; register manually:"
        echo "      claude mcp add --scope user cc-context -- \"${PYBIN}\" -m cc_context.cli"
    fi
fi

if [ "${CC_INSTALL_SKIP_STATUSLINE:-}" = "1" ]; then
    echo "==> Skipping statusLine config (CC_INSTALL_SKIP_STATUSLINE=1)"
elif ! command -v jq >/dev/null 2>&1; then
    echo "==> Configuring statusLine: jq not found; add this to ${SETTINGS} yourself:"
    echo "      \"statusLine\": { \"type\": \"command\", \"command\": \"<path>/statusline-wrapper.sh\" }"
else
    echo "==> Configuring statusLine (so the context dump is produced)"
    chmod +x "${WRAPPER}" 2>/dev/null || true
    if [ -f "${SETTINGS}" ] && ! jq -e . "${SETTINGS}" >/dev/null 2>&1; then
        # settings.json exists but doesn't parse as JSON (malformed, or unreadable).
        # Skip rather than abort a half-done install (the MCP server is already registered).
        echo "    cannot parse ${SETTINGS} as JSON — skipping statusLine."
        echo "    fix it, then set statusLine.command = ${WRAPPER} yourself,"
        echo "    or re-run with CC_INSTALL_SKIP_STATUSLINE=1 to silence this."
    elif [ -f "${SETTINGS}" ] && [ -n "$(jq -r '.statusLine.command // empty' "${SETTINGS}" 2>/dev/null)" ]; then
        existing="$(jq -r '.statusLine.command' "${SETTINGS}")"
        echo "    settings.json already has a statusLine; NOT overwriting:"
        echo "      ${existing}"
        echo "    To also capture the dump, set statusLine.command to the wrapper and have it"
        echo "    call your command via CLAUDE_CONTEXT_WRAPPED_CMD (see README 'statusLine users')."
    else
        mkdir -p "$(dirname -- "${SETTINGS}")"
        if [ -f "${SETTINGS}" ]; then
            # timestamped backup (never clobber a previous backup) + atomic same-dir rename
            cp -- "${SETTINGS}" "${SETTINGS}.cc-context.bak.$(date +%Y%m%d%H%M%S%N)"
            tmp="$(mktemp -- "${SETTINGS}.XXXXXX")"
            jq --arg cmd "${WRAPPER}" '.statusLine = {type:"command", command:$cmd}' "${SETTINGS}" > "${tmp}"
            mv -- "${tmp}" "${SETTINGS}"
            echo "    backed up + set statusLine.command = ${WRAPPER}"
        else
            # build with jq so any special chars in the path are JSON-escaped (no string interpolation)
            jq -n --arg cmd "${WRAPPER}" '{statusLine: {type:"command", command:$cmd}}' > "${SETTINGS}"
            echo "    created ${SETTINGS} with statusLine.command = ${WRAPPER}"
        fi
    fi
fi

echo
echo "Done. Open a NEW Claude Code session; after one assistant turn, ask Claude to run"
echo "get_current_context_usage (the cc-context MCP tool)."
