# claudecmd

A small, reliable command that drives your **local, already-installed Claude
Code** *interactive* session programmatically — from scripts, shell pipelines,
and editor integrations — and returns the assistant's reply as plain text or a
stable JSON envelope.

It drives the **interactive** session (not `claude -p`) on purpose: Claude Code
prices `-p`/headless usage separately from interactive sessions, so `claudecmd`
keeps automated calls on your interactive (subscription) path. There is no
network server and no API key handling of its own — it shells out to the
`claude` binary you already use, under a pseudo-terminal.

> The PyPI **package** is `pyclacmd`; the installed **command** is `claudecmd`.

```bash
claudecmd "say hello"
echo "summarize this" | claudecmd
git diff | claudecmd "Review this diff for risky changes"
claudecmd --json "explain this repo"
claudecmd --session 8f3c… "continue from previous context"
```

## Demo

![claudecmd demo](assets/demo.gif)

---

## Requirements

- **macOS** (primary target; also works on Linux).
- **Python 3.8+**.
- **Claude Code installed and authenticated.** `claudecmd` invokes the `claude`
  binary found on your `PATH`. Validate your setup:

  ```bash
  command -v claude
  claude --version
  claude "say hello"      # interactive session works for your login
  ```

  Authentication (`claude /login` or a subscription token) is a prerequisite —
  `claudecmd` does not manage it. Point `claudecmd` at a specific binary with
  the `CLAUDECMD_CLAUDE_BIN` environment variable.

---

## Install

```bash
pip install pyclacmd
```

This provides the `claudecmd` console script. `pexpect` and `pyte` (used to
drive and render the interactive TUI) are installed automatically.

> **macOS note:** if the system `pip` is too old, use a virtualenv:
>
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install pyclacmd
> ```

---

## Usage

```text
claudecmd [options] [prompt]
```

The prompt comes from (in priority order): the positional argument, then piped
STDIN. If both are present they are combined:

```text
<positional prompt>

--- STDIN ---
<stdin content>
```

### Flags

| Flag | Description |
| --- | --- |
| `--json` | Emit a stable JSON envelope (see below). |
| `--raw` | Print the full rendered TUI screen (debugging aid). |
| `--cwd <path>` | Working directory Claude runs in. |
| `--session <id-or-name>` | Resume a session by UUID or local name. |
| `--timeout <seconds>` | Abort (and clean up) after N seconds. |
| `--model <model>` | Model alias (`opus`, `sonnet`, `haiku`) or full id. |
| `--tools <tools>` | Built-in tools to allow (e.g. `"Bash,Read"`); `""` disables all. |
| `--permission-mode <mode>` | Claude permission mode (e.g. `plan`, `acceptEdits`). |
| `--system-prompt <text>` | Replace the system prompt. |
| `--append-system-prompt <text>` | Append to the system prompt. |
| `--allowed-tools <patterns>` | Permission allow patterns, e.g. `"Bash(git:*),Read"`. |
| `--disallowed-tools <patterns>` | Permission deny patterns. |
| `--add-dir <path>` | Extra allowed directory (repeatable). |
| `--debug` | Emit redacted diagnostics to stderr; keep oversize-stdin temp files. |
| `--dry-run` | Print the command plan and exit without calling Claude. |
| `--version` / `--help` | Standard. |

### Examples

```bash
# Basic
claudecmd "explain this repo"

# Pipe input as JSON
cat task.md | claudecmd --json

# Review a git diff
git diff | claudecmd "Review for risky changes and return concise findings"

# Unattended: disable tools so no permission prompt can stall the run
claudecmd --tools "" "summarize the open questions in this file"

# See exactly what would run, without running it
claudecmd --dry-run "say hello"
```

---

## Output contract

### Default (human) mode

Prints **only** the assistant's final reply to stdout, extracted from the
rendered session. No banners, no metadata.

### `--json` mode

Emits one JSON object:

```json
{
  "ok": true,
  "result": "assistant response text",
  "session_id": null,
  "duration_ms": 6824,
  "cost_usd": null,
  "raw": null,
  "mode": "interactive"
}
```

`session_id`, `cost_usd`, and `raw` are `null` — the interactive TUI does not
expose them. On failure:

```json
{ "ok": false, "error": "…", "kind": "claude_timeout", "exit_code": 124, "duration_ms": 1234 }
```

### `--raw` mode

Prints the full rendered TUI screen unchanged — useful for debugging extraction.

### `--dry-run` mode

Prints the exact command plan (run through the secret redactor) and exits:

```json
{ "ok": true, "dry_run": true, "command": ["claude", "say hello", "--model", "haiku"] }
```

---

## How it works

`claudecmd` spawns `claude "<prompt>"` (interactive, no `-p`) under a
pseudo-terminal, renders the TUI with a real terminal emulator (`pyte`) so
layout and whitespace survive, auto-answers the one-time workspace-trust dialog
for `--cwd`, waits for the turn to settle, and extracts the assistant's reply
from the rendered screen.

**Caveats** — it scrapes a human-facing TUI, so it is inherently less robust
than a headless API:

- No `session_id` or `cost_usd` is available (the TUI does not expose them).
- Completion is detected heuristically (the reply settles and the input box
  returns). Give long replies a larger `--timeout`.
- A tool-permission prompt will stall an unattended run — pass `--tools ""` to
  disable tools, or an appropriate `--permission-mode`.
- Extraction is tuned to Claude Code's current TUI (v2.1.x) and may need
  updating if the interface changes.

---

## Sessions

- A `--session` value that is a **UUID** is resumed directly (`--resume`).
- A **friendly name** is looked up in `~/.claudecmd/sessions.json` (override the
  directory with `CLAUDECMD_HOME`) and resumed if present. Note: because the
  interactive TUI does not surface the session id, `claudecmd` cannot *record* a
  new name→id mapping on this path — pre-seed names or resume by UUID.

---

## Large input

STDIN larger than the guard (default **9 MB**) is **not** silently truncated. It
is written to a restrictive (`0600`) temp file under the OS temp directory, and
the prompt references that file path so Claude can read it. The temp file is
deleted after the run unless `--debug` is set.

---

## Error kinds

Every failure carries a stable `kind` (the `kind` field in `--json` mode; in the
stderr message otherwise) and a non-zero exit code:

| Kind | Exit | Meaning |
| --- | --- | --- |
| `claude_not_found` | 127 | The `claude` binary was not found / not executable. |
| `claude_auth_required` | 2 | Claude reported an authentication problem. |
| `claude_timeout` | 124 | The run exceeded `--timeout`. |
| `cwd_not_found` | 66 | `--cwd` is not an existing directory. |
| `session_store_error` | 74 | The session mapping file could not be read/written. |
| `pty_unavailable` | 69 | `pexpect`/`pyte` could not be imported. |
| `no_prompt` | 64 | No prompt via argument or stdin. |
| `unknown` | 1 | Anything else (including no extractable reply). |

---

## Security notes

- Prompts and flags are passed as a subprocess **argument array** — never
  interpolated into a shell string, so there is no shell-injection surface.
- Prompts are not written to disk except for the oversize-stdin case above.
- Temp files and the session store use restrictive permissions.
- `--debug` output and the `--dry-run` command plan are run through a
  best-effort secret redactor (API keys, bearer tokens, `Authorization:`
  headers, `.env`-style assignments).
- No permission-bypass flags are enabled by default. `--permission-mode` is a
  passthrough: explicitly passing `bypassPermissions` opts into Claude Code's
  auto-approve behavior — a deliberate choice, never a default.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite mocks the `claude` binary / interactive runner, so **CI never
requires a real Claude login**. GitHub Actions runs `pytest` on Python 3.12 /
Ubuntu; the package itself supports Python 3.8+.

## License

MIT — see [LICENSE](LICENSE).
