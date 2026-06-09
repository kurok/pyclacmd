# Changelog

All notable changes to **pyclacmd** (the `claudecmd` command). This project
follows [semantic versioning](https://semver.org/).

## 0.2.2

- Discoverability: richer PyPI metadata (summary, keywords, classifiers,
  project links), README badges, and this changelog. No behavior change.

## 0.2.1

- Fix: with a multi-line prompt (positional argument + piped STDIN), the
  interactive TUI echoes the whole prompt and reply extraction leaked the
  `--- STDIN ---` continuation into the output. Extraction now anchors on the
  first assistant bullet after the prompt echo, so only the reply is returned.
- Refreshed the README demo GIF to show interactive mode.

## 0.2.0

- **Breaking:** interactive-only. Removed the `claude -p`/headless path and its
  flags (`--stream`, `--pty`, `--no-session-persistence`, `--max-turns`,
  `--max-budget-usd`); the old `--interactive` flag is now implicit.
- `claudecmd` now always drives Claude Code's interactive session under a
  pseudo-terminal and emits the parsed reply (text, `--json`, or `--raw`),
  keeping automated calls on the interactive (subscription) path.
- `pexpect` and `pyte` are now core dependencies.

## 0.1.0

- Initial release: a thin wrapper around `claude -p` with a stable output
  contract (text / `--json` / `--stream` / `--raw`), session handling,
  timeouts, a structured error taxonomy, secret redaction, and a PTY fallback.
