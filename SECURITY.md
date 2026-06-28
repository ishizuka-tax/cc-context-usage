# Security Policy

## Reporting a Vulnerability

If you discover a potential security vulnerability in this project, **please do not file a public issue**. Instead, use one of the following private channels:

1. **GitHub Security Advisories** (preferred) — open a private advisory via the repository's *Security → Advisories* tab.
2. **GitHub Discussions** (private category, if enabled).

We aim to acknowledge reports within 7 days, but please understand this project is maintained by a single individual on a part-time basis. Response time may vary; see the maintenance policy in the README for context.

## What this project does

`cowork-context-usage` is a read-only observability skill. It lets Claude report its own context-window usage by reading **local** session files:

- **Claude Desktop recipe**: a host-side MCP server (`mcp-server/server.py`) reads `audit.jsonl` and `local_<sessionId>.json` from the local Claude Desktop session directory.
- **Claude Code CLI recipe**: a `jq` query reads the local `/tmp/cc-context-*.json` dump produced by the bundled statusLine wrapper.

The project **does not transmit any data over the network**. It only reads local files and returns token counts / session metadata to the calling Claude session.

## Security-sensitive areas

- **Local file reads** (`mcp-server/server.py`) — the MCP server has read access to the session directory, which can contain conversation transcripts. The server extracts only token usage and selected metadata fields; it does not read or forward message content. Review `compute_context_usage` / `get_session_meta` if you need to confirm exactly which fields are surfaced.
- **Dump file location** (`scripts/statusline-wrapper.sh`) — the wrapper writes the full statusLine stdin JSON (not just token counts) to `/tmp/cc-context-<session_id>.json`. It is created via `mktemp` (mode `0600`, owner-only) then moved into place, so it is not world-readable by default. On shared/multi-user hosts, set `CLAUDE_CONTEXT_DUMP_DIR` to a private directory (e.g. `$XDG_RUNTIME_DIR`) and clean up old dumps as needed.
- **Session ID in filename** (`scripts/statusline-wrapper.sh`) — the session id is sanitized (alphanumeric + `-` only) before being used in the dump filename.

## Out of Scope

- Hardening of the underlying OS, Claude Desktop, or Claude Code installation.
- Security of the local session files themselves (they are managed by Claude Desktop / Claude Code).
- The `mcp` SDK, `jq`, `ccstatusline`, or any other third-party dependency — report those to their respective projects.
- HMAC signature verification of `audit.jsonl` is intentionally not implemented (see `mcp-server/IMPL_NOTES.md`); tamper detection of session files is out of scope.

## Coordinated Disclosure

We support coordinated disclosure timelines. If you would like a CVE assigned, please indicate so in your report and we will work with you to coordinate publication.
