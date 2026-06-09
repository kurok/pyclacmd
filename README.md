# claudecmd

A small, reliable command-line facade that lets scripts, shell pipelines, and
editor integrations call your **local, already-installed Claude Code**
programmatically — with a stable output contract, session handling, timeouts,
structured errors, and an optional PTY fallback.

It is a thin wrapper around `claude -p` (Claude Code's print/headless mode), not
a replacement for interactive Claude Code. There is no network server and no
API key handling of its own — it shells out to the `claude` binary you already
use.

```bash
claudecmd "say hello"
echo "summarize this" | claudecmd
git diff | claudecmd "Review this diff for risky changes"
claudecmd --json "explain this repo"
claudecmd --stream "explain the current architecture"
claudecmd --session auth-refactor "continue from previous context"
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
  claude -p "say hello" --output-format json
  ```

  Install Claude Code via the Anthropic install script or Homebrew cask (npm
  global installs are not assumed). Authentication (`claude /login` or
  `ANTHROPIC_API_KEY`) is a prerequisite — `claudecmd` does not manage it.

You can point `claudecmd` at a specific binary with the `CLAUDECMD_CLAUDE_BIN`
environment variable.

---

## Install

### Option A — run from a checkout (no install)

The repository ships an executable shim; nothing to install:

```bash
git clone https://github.com/kurok/pyclacmd
cd pyclacmd
./bin/claudecmd "say hello"
```

### Option B — install the `claudecmd` command

```bash
pip install .
# or, for development:
pip install -e ".[dev]"
```

This provides a `claudecmd` console script.

> **macOS note:** the system `pip` shipped with the OS Python can be old enough
> that `pip install -e .` fails with a `--user`/`--prefix` conflict. If you hit
> that, use a virtualenv (recommended), `pipx install .`, or just use the
> `./bin/claudecmd` shim above.
>
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -e ".[dev]"
> ```

The PTY fallback needs `pexpect`, which is an optional extra:

```bash
pip install ".[pty]"
```

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
| `--stream` | Stream assistant text progressively as it is produced. |
| `--raw` | Print Claude Code's response exactly as returned. |
| `--cwd <path>` | Working directory Claude runs in. |
| `--session <id-or-name>` | Resume/track a session by UUID or friendly name. |
| `--timeout <seconds>` | Abort (and clean up) after N seconds. |
| `--model <model>` | Model alias (`opus`, `sonnet`) or full id. |
| `--max-turns <n>` | Max agent turns (forwarded to Claude Code). |
| `--max-budget-usd <amount>` | Spend ceiling for the run. |
| `--system-prompt <text>` | Replace the system prompt. |
| `--append-system-prompt <text>` | Append to the system prompt. |
| `--allowed-tools <tools>` | e.g. `"Bash(git:*),Read"` (sent as `--allowedTools`). |
| `--disallowed-tools <tools>` | Tools to deny (sent as `--disallowedTools`). |
| `--permission-mode <mode>` | Claude permission mode (e.g. `plan`, `acceptEdits`). |
| `--no-session-persistence` | Do not persist or resume the session. |
| `--pty` | Force execution inside a pseudo-terminal (needs `pexpect`). |
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

# Stream output
claudecmd --stream "explain the current architecture"

# Named session (resumes automatically on the next call with the same name)
claudecmd --session auth-refactor "continue from previous context"

# Constrain tools and run in a specific directory
claudecmd --cwd ~/src/app --allowed-tools "Bash(git:*),Read" "summarize recent changes"

# See exactly what would run, without running it
claudecmd --dry-run "say hello"
```

---

## Output contract

### Default (human) mode

Prints **only** the final assistant result to stdout. No banners, no metadata.
Diagnostics go to stderr only on error, or when `--debug` is set.

### `--json` mode

Always emits one JSON object.

**Success:**

```json
{
  "ok": true,
  "result": "assistant response text",
  "session_id": "84cf2949-2329-4211-9526-1d8935ee9ab9",
  "duration_ms": 3845,
  "cost_usd": 0.0289945,
  "raw": { "...": "the full Claude Code JSON response" }
}
```

**Failure:**

```json
{
  "ok": false,
  "error": "Claude command failed",
  "kind": "claude_exit_nonzero",
  "exit_code": 1,
  "stderr": "...",
  "duration_ms": 1234
}
```

### `--dry-run` mode

Prints the exact command plan and exits without invoking Claude. In `--json`
mode it emits a dedicated envelope:

```json
{ "ok": true, "dry_run": true, "command": ["claude", "-p", "say hello", "--output-format", "json"] }
```

Secrets in the plan are run through the redactor.

### `--raw` mode

Prints Claude Code's raw response unchanged. Combine with `--stream` to emit raw
newline-delimited stream JSON without transformation.

### `--stream` mode

Streams assistant text to stdout as it arrives. `--raw --stream` emits the raw
stream-json event lines instead.

---

## Error kinds

Every failure carries a stable `kind` (in `--json` mode, the `kind` field; in
default mode, in the stderr message) and a non-zero exit code:

| Kind | Exit | Meaning |
| --- | --- | --- |
| `claude_not_found` | 127 | The `claude` binary was not found / not executable. |
| `claude_auth_required` | 2 | Claude reported an authentication problem. |
| `claude_exit_nonzero` | (Claude's) | Claude exited non-zero; its code is preserved. |
| `claude_timeout` | 124 | The run exceeded `--timeout`. |
| `invalid_json` | 65 | Claude's output could not be parsed as JSON. |
| `stdin_too_large` | 64 | Reserved for stdin guard failures. |
| `cwd_not_found` | 66 | `--cwd` is not an existing directory. |
| `session_store_error` | 74 | The session mapping file could not be read/written. |
| `pty_unavailable` | 69 | PTY fallback requested but `pexpect` is missing. |
| `no_prompt` | 64 | No prompt via argument or stdin. |
| `unknown` | 1 | Anything else. |

---

## Sessions

- A `--session` value that is a **UUID** is resumed directly (`--resume`).
- A **friendly name** is mapped to the session id Claude returns, in
  `~/.claudecmd/sessions.json` (override the directory with `CLAUDECMD_HOME`).
  The next call with the same name resumes that conversation automatically.
- The store is created with `0700`/`0600` permissions, written atomically, and
  guarded with file locking to survive concurrent runs.

Example mapping:

```json
{
  "auth-refactor": {
    "session_id": "00000000-0000-0000-0000-000000000000",
    "created_at": "2026-06-09T12:00:00Z",
    "updated_at": "2026-06-09T12:15:00Z",
    "cwd": "/Users/example/src/repo"
  }
}
```

---

## Large input

STDIN larger than the guard (default **9 MB**, just under Claude Code's ~10 MB
stdin cap) is **not** silently truncated. It is written to a restrictive
(`0600`) temp file under the OS temp directory, and the prompt references that
file path so Claude can read it. The temp file is deleted after the run unless
`--debug` is set.

---

## Security notes

- Prompts and flags are passed as a subprocess **argument array** — never
  interpolated into a shell string, so there is no shell-injection surface.
- Prompts are not written to disk except for the oversize-stdin case above.
- Temp files and the session store use restrictive permissions.
- `--debug` output and the `--dry-run` command plan are run through a
  best-effort secret redactor (API keys, bearer tokens, `Authorization:`
  headers, `.env`-style assignments).
- No permission-bypass flags are enabled by default, and
  `--dangerously-skip-permissions` is intentionally **not** exposed. Note that
  `--permission-mode` is a passthrough: a user who explicitly passes
  `--permission-mode bypassPermissions` opts into Claude Code's auto-approve
  behavior. That is a deliberate, explicit choice — never a default.

---

## Debug behavior

`--debug` writes redacted diagnostics to **stderr** (the chosen command, the
resolved session, retries). In `--json` mode the structured envelope still goes
to stdout; extra detail goes to stderr only with `--debug`. Oversize-stdin temp
files are kept (and their paths logged) when debugging.

---

## PTY fallback

`claude -p` is the default and works headlessly. A PTY path exists for the rare
environment that demands a real terminal: it spawns `claude` under a
pseudo-terminal (via `pexpect`), captures output, strips ANSI / Kitty keyboard
escape sequences (a known macOS Terminal.app nuisance), and forwards terminal
resizes. It is used when you pass `--pty`, or automatically as a fallback if a
normal run fails with a TTY-related error. PTY output is plain text only, so
session id and cost metadata are not available on that path.

---

## Known limitations

- `--max-turns` is forwarded to Claude Code as-is; some native Claude Code
  builds do not expose that flag and will reject it (surfaced as
  `claude_exit_nonzero` with Claude's own message).
- `--json` is ignored for envelope purposes in `--stream` mode (streaming has
  its own contract; use `--raw --stream` for raw event lines).
- First-party HTTP/OpenAI-compatible server, daemon, and Windows/WSL support are
  intentionally out of scope for this version.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite mocks the `claude` binary, so **CI never requires a real Claude
login**. GitHub Actions runs `pytest` on Python 3.12 / Ubuntu (see
`.github/workflows/ci.yml`); the package itself supports Python 3.8+.

### Manual macOS smoke tests

```bash
claudecmd "say hello"
echo "say hello" | claudecmd
claudecmd --json "say hello"
claudecmd --stream "say hello"
claudecmd --cwd /tmp "pwd"
claudecmd --timeout 5 "say hello"
claudecmd --dry-run "say hello"
claudecmd --session test-session "remember: project is claudecmd"
claudecmd --session test-session "what is the project?"
```

## License

MIT — see [LICENSE](LICENSE).
