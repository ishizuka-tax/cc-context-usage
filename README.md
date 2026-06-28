# cc-context-usage

**English** | [日本語](README.ja.md)

Let **Claude** (the LLM) read its **own** context-window usage as a real number —
across both **Claude Desktop** (Cowork / local agent mode) and the **Claude Code CLI** —
without the side effects of the `/context` slash command.

## Why

`/context` reports an *estimate* of the next turn and has side effects. This tool instead
reads the **actual** input tokens of the most recent API request
(`input + cache_creation + cache_read`) — the same input-only basis as the
[Claude Code statusLine `used_percentage`](https://code.claude.com/docs/en/statusline).

That number is for **context-window monitoring** — a different concept from billing and
rate limits (cache reads are cheaper for billing and are excluded from ITPM rate limits on
most models). It can be invoked by Claude itself via an MCP tool, so it suits *self-checks*
before deciding whether to split a session, hand off, or trim scope — with the actual
number in hand rather than a guess.

## Architecture

One Python package, two thin MCP servers over a shared core; the mechanism differs per
environment but the LLM-facing tool and output shape are the same.

```
src/cc_context/
  core.py          shared: normalization / token limits / contract / rate-limit formatting
  audit_source.py  Desktop adapter: reads the session audit.jsonl
  dump_source.py   CLI adapter: reads the statusLine dump (+ fail-loud schema validation)
  desktop.py       MCP server entrypoint for Claude Desktop  (cc-context-desktop)
  cli.py           MCP server entrypoint for Claude Code CLI (cc-context-cli)
  limits.json      per-model context-window limits (package data, loaded via importlib.resources)
scripts/statusline-wrapper.sh   produces the dump the CLI adapter reads
```

Both servers register as the MCP server **`cc-context`** and expose
`get_current_context_usage` returning the same normalized JSON. There is **no runtime
routing**: you install the adapter that fits your environment.

## Working directory & where it installs

**Choose a permanent location first, clone there, then install** — the directory you clone
into *is* the install location, not a throwaway you copy from. (If you move the clone later,
re-run `install-cli.sh` from the new location to re-wire the paths.)

- **Working directory doesn't matter.** `install-cli.sh` derives every path from its own
  location (and `$HOME`), not from your current directory, and registers the MCP at
  **user scope** — so it works from any session regardless of each session's `cwd`. You can
  run it as `bash /path/to/cc-context-usage/scripts/install-cli.sh` or after `cd`-ing in; the
  result is identical.
- **Keep the clone where it is — this is a clone-and-run-in-place install.** After installing,
  the repo is still referenced at runtime: `statusLine.command` points at
  `scripts/statusline-wrapper.sh` **inside the clone** (run on every turn, not copied), and the
  venv is created at `.venv` **inside the clone** by default. **Deleting or moving the clone
  breaks statusLine and the MCP.** The Python package itself is copied into the venv (a regular,
  non-editable `pip install`), so `src/` is not read at runtime — but the wrapper script and the
  venv are. To make the clone removable, install the venv elsewhere
  (`install-cli.sh /path/to/venv`) **and** copy the wrapper to a stable path and point
  `statusLine.command` there yourself.

## Install — Claude Desktop (Cowork)

**Quick (Windows):** `powershell -ExecutionPolicy Bypass -File scripts\install-desktop.ps1`
— creates a venv, installs the package, and merges the `cc-context` entry into
`claude_desktop_config.json` (backing it up first). Then restart Claude Desktop.
(It auto-detects a working interpreter — the `py` launcher, then `python`/`python3` —
and ignores the Microsoft Store alias stub; override with `-PythonExe py` if needed.)
Manual steps:

```bash
pip install .
```

Register in `claude_desktop_config.json` (`command` = your venv's python; args launch the
desktop entrypoint):

```json
{
  "mcpServers": {
    "cc-context": {
      "command": "/abs/path/to/.venv/bin/python",
      "args": ["-m", "cc_context.desktop"]
    }
  }
}
```

Restart Claude Desktop. Ask Claude to run `get_current_context_usage`.
(`get_context_history` and `get_session_meta` are also available; `get_session_meta`
deliberately does **not** return PII such as email / cwd / process names.)

## Install — Claude Code CLI

**Quick:** `scripts/install-cli.sh` — creates a venv, installs the package, registers the
`cc-context` MCP server (`claude mcp add`, user scope), and points statusLine at the bundled
wrapper (backs up `settings.json`, never overwrites an existing statusLine). If `settings.json`
doesn't parse as JSON, the statusLine step is skipped gracefully (the install still registers
the MCP server) — or pass `CC_INSTALL_SKIP_STATUSLINE=1` if you wire statusLine yourself.
Manual steps — two pieces, the wrapper captures the number, the MCP server serves it:

1. **statusLine wrapper** (captures the authoritative number to a dump file). In
   `~/.claude/settings.json`:

   ```jsonc
   "statusLine": {
     "type": "command",
     "command": "/abs/path/to/scripts/statusline-wrapper.sh"
   }
   ```

   The authoritative `used_percentage` is only delivered to the statusLine command, so this
   capture step is required.

2. **MCP server** (reads the dump). Register `cc-context-cli` with Claude Code's MCP config
   (`python -m cc_context.cli`). After one assistant turn, `get_current_context_usage`
   returns the usage. Register at **user scope** (`claude mcp add --scope user …`) so the
   tool is available in every session; the default `local` scope binds to the directory you
   ran the command in.

## Interpreting the value (opinion — not normative)

The tool returns facts; what a given percentage *means for you* depends on your model,
workflow, and tolerance. As a personal rule of thumb (**an example, not a prescription**):
~30% comfortable / 60–80% worth a look / 80%+ consider splitting. Tune to your own setup —
the tool intentionally does not bake thresholds in.

## No-Python CLI users

If you would rather not install the Python MCP server, the dump file is plain JSON; you can
read it directly (example, not a maintained interface):

```bash
jq '.context_window.used_percentage' "$(ls -t /tmp/cc-context-*.json | head -1)"
```

## statusLine users

The wrapper passes through to **ccstatusline** for display if installed, and falls back to
dump-only mode otherwise — so the two supported setups are **ccstatusline users** and
**users with no statusLine**. If you already use a *different* statusLine command, point the
wrapper at it via `CLAUDE_CONTEXT_WRAPPED_CMD` (or read the wrapper and adapt it) — that
case is DIY, not officially supported.

## Privacy / local data

The statusLine wrapper writes the **full** statusLine JSON from Claude Code to
`$CLAUDE_CONTEXT_DUMP_DIR/cc-context-<session_id>.json` (default `/tmp`). That payload
includes session metadata such as your working directory and cost figures. It **stays on
your machine** — this tool never transmits it anywhere — but on shared or multi-user hosts
you may want to point `CLAUDE_CONTEXT_DUMP_DIR` at a private directory and/or clean it up.

The MCP tools themselves return only **basenames** (e.g. `audit.jsonl`), never absolute
paths, so your username / machine layout is not exposed in the tool output.

## Uninstall

- **CLI:** `scripts/uninstall-cli.sh` — unregisters the `cc-context` MCP server (user scope),
  reverts `statusLine` only if it still points at this repo's wrapper (backing it up first),
  and removes the venv.
- **Desktop (Windows):** `powershell -ExecutionPolicy Bypass -File scripts\uninstall-desktop.ps1`
  — removes the `cc-context` entry from `claude_desktop_config.json` (backup first; other
  entries preserved) and removes the venv. Restart Claude Desktop afterward.

## Verification posture

This is a public edition derived from the maintainer's internal setup; it is **not
continuously dogfooded here**. Correctness is guaranteed by the repo's own checks: CI runs
the pytest suite (core + both adapters, with synthetic fixtures) and shellcheck on the
wrapper. Maintenance is part-time, no SLA; design discussions welcome via Discussions.

## License

[Apache-2.0](LICENSE). See [`NOTICE`](NOTICE) and [`SECURITY.md`](SECURITY.md).
