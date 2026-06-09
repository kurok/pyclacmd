"""``claudecmd`` command-line entry point.

Orchestrates: argument parsing -> prompt collection -> session resolution ->
command construction -> execution -> output formatting, with a structured
error taxonomy and stable exit codes.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import List, Optional

from . import __version__
from .claude_command import (
    ClaudeOptions,
    OUTPUT_JSON,
    OUTPUT_STREAM_JSON,
    build_command,
)
from .errors import (
    ClacmdError,
    CLAUDE_AUTH_REQUIRED,
    CLAUDE_EXIT_NONZERO,
    CWD_NOT_FOUND,
    NO_PROMPT,
    UNKNOWN,
)
from .prompt import DEFAULT_MAX_STDIN_BYTES, cleanup_temp_files, collect_prompt, read_stdin
from .redact import redact, redact_argv
from . import output as output_mod
from . import pty_runner
from . import runner as runner_mod
from .session_store import SessionStore

import os

# stderr substrings that indicate Claude needs authentication.
_AUTH_MARKERS = (
    "invalid api key",
    "authentication_error",
    "please run `claude",
    "please run claude",
    "run `claude /login`",
    "not authenticated",
    "not logged in",
    "you must log in",
    "unauthorized",
    "oauth token",
    "credit balance",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claudecmd",
        description="Programmatic, scriptable wrapper around Claude Code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", nargs="?", help="Prompt text (or pipe via stdin)")
    parser.add_argument("--json", action="store_true", help="Emit a stable JSON envelope")
    parser.add_argument("--stream", action="store_true", help="Stream assistant text progressively")
    parser.add_argument("--raw", action="store_true", help="Emit Claude's raw output unchanged")
    parser.add_argument("--cwd", metavar="PATH", help="Working directory for Claude")
    parser.add_argument("--session", metavar="ID-OR-NAME", help="Resume/track a session by UUID or local name")
    parser.add_argument("--timeout", type=float, metavar="SECONDS", help="Abort after SECONDS")
    parser.add_argument("--model", help="Model alias or full name")
    parser.add_argument("--max-turns", type=int, dest="max_turns", help="Max agent turns (forwarded to Claude)")
    parser.add_argument("--max-budget-usd", type=float, dest="max_budget_usd", help="Max USD to spend")
    parser.add_argument("--system-prompt", dest="system_prompt", help="Replace the system prompt")
    parser.add_argument("--append-system-prompt", dest="append_system_prompt", help="Append to the system prompt")
    parser.add_argument("--allowed-tools", dest="allowed_tools", help='e.g. "Bash(git:*),Read"')
    parser.add_argument("--disallowed-tools", dest="disallowed_tools", help="Tools to deny")
    parser.add_argument("--permission-mode", dest="permission_mode", help="Claude permission mode")
    parser.add_argument(
        "--no-session-persistence",
        action="store_true",
        dest="no_session_persistence",
        help="Do not persist/resume the session",
    )
    parser.add_argument("--pty", action="store_true", help="Force execution inside a PTY")
    parser.add_argument("--debug", action="store_true", help="Emit diagnostics to stderr (redacted)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Print the command plan, do not run Claude")
    parser.add_argument(
        "--max-stdin-bytes",
        type=int,
        default=DEFAULT_MAX_STDIN_BYTES,
        dest="max_stdin_bytes",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--version", action="version", version="claudecmd {}".format(__version__)
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    def dbg(message: str) -> None:
        if args.debug:
            sys.stderr.write("[claudecmd] " + redact(str(message)) + "\n")

    temp_files: List[str] = []
    try:
        if args.cwd and not os.path.isdir(args.cwd):
            raise ClacmdError(
                CWD_NOT_FOUND, "cwd not found or not a directory: {}".format(args.cwd)
            )

        stdin_text = read_stdin()
        if not (args.prompt and args.prompt.strip()) and not stdin_text:
            # Route through the structured error path so --json still gets an
            # envelope and the documented `no_prompt`/exit-64 contract holds.
            if not args.json:
                parser.print_usage(sys.stderr)
            raise ClacmdError(
                NO_PROMPT,
                "No prompt provided. Pass a prompt argument or pipe data via stdin.",
            )

        prompt, temp_files = collect_prompt(
            args.prompt,
            stdin_text,
            max_stdin_bytes=args.max_stdin_bytes,
            debug=args.debug,
        )

        store = SessionStore()
        resume_id = store.resolve(args.session) if args.session else None
        if args.session:
            dbg("session {!r} resolved to {}".format(args.session, resume_id or "(new)"))

        options = ClaudeOptions(
            model=args.model,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget_usd,
            system_prompt=args.system_prompt,
            append_system_prompt=args.append_system_prompt,
            allowed_tools=args.allowed_tools,
            disallowed_tools=args.disallowed_tools,
            permission_mode=args.permission_mode,
            no_session_persistence=args.no_session_persistence,
            resume_session_id=resume_id,
            cwd=args.cwd,
        )

        output_format = OUTPUT_STREAM_JSON if args.stream else OUTPUT_JSON
        command = build_command(prompt, options, output_format=output_format)
        dbg("command: " + " ".join(shlex.quote(a) for a in redact_argv(command)))

        if args.dry_run:
            return _print_dry_run(command, args)

        if args.pty:
            return _run_pty(command, args, store, prompt)
        if args.stream:
            return _run_stream(command, args, store)
        return _run_normal(command, args, store, dbg)

    except ClacmdError as exc:
        dbg("error: {} [{}]".format(exc.message, exc.kind))
        return _fail(exc, args, exc.extra.get("duration_ms"))
    except BrokenPipeError:
        # Downstream consumer closed the pipe (e.g. `claudecmd ... | head`).
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except Exception as exc:  # last-resort safety net; never dump a traceback
        return _fail(ClacmdError(UNKNOWN, str(exc) or exc.__class__.__name__), args, None)
    finally:
        if temp_files and not args.debug:
            cleanup_temp_files(temp_files)
        elif temp_files and args.debug:
            dbg("kept temp file(s): {}".format(", ".join(temp_files)))


# --- execution paths --------------------------------------------------------
def _run_normal(command, args, store, dbg) -> int:
    try:
        result = runner_mod.run(command, cwd=args.cwd, timeout=args.timeout)
    except ClacmdError as exc:
        if not args.pty and pty_runner.looks_like_tty_error(exc.message):
            dbg("retrying under PTY after TTY-related failure")
            return _run_pty(command, args, store, None)
        raise

    if result.returncode != 0:
        if not args.pty and pty_runner.looks_like_tty_error(result.stderr):
            dbg("retrying under PTY after TTY-related stderr")
            return _run_pty(command, args, store, None)
        raise _classify_exit(result)

    data = output_mod.parse_claude_json(result.stdout)
    session_id = output_mod.extract_session_id(data)
    cost = output_mod.extract_cost(data)
    text = output_mod.extract_result_text(data)

    _maybe_update_session(store, args, session_id)

    if args.raw:
        _write_stdout(result.stdout)
    elif args.json:
        envelope = output_mod.success_envelope(
            text, session_id, result.duration_ms, cost, data
        )
        _write_stdout(json.dumps(envelope, ensure_ascii=False))
    else:
        _write_stdout(text)
    return 0


def _run_stream(command, args, store) -> int:
    processor = output_mod.StreamProcessor(raw=args.raw)
    result = runner_mod.run_stream(
        command, cwd=args.cwd, timeout=args.timeout, on_line=processor.handle_line
    )
    if result.returncode != 0:
        raise _classify_exit(result)
    _maybe_update_session(store, args, processor.session_id)
    return 0


def _run_pty(command, args, store, prompt) -> int:
    text = pty_runner.run_pty(command, cwd=args.cwd, timeout=args.timeout)
    # PTY output is plain text; no JSON envelope/session metadata available.
    if args.json:
        envelope = output_mod.success_envelope(text, None, None, None, None)
        _write_stdout(json.dumps(envelope, ensure_ascii=False))
    else:
        _write_stdout(text)
    return 0


# --- helpers ----------------------------------------------------------------
def _maybe_update_session(store: SessionStore, args, session_id: Optional[str]) -> None:
    if not args.session or not session_id or args.no_session_persistence:
        return
    try:
        store.update(args.session, session_id, cwd=args.cwd)
    except ClacmdError as exc:
        # Session bookkeeping must never fail an otherwise-successful run.
        if args.debug:
            sys.stderr.write("[claudecmd] session store update failed: {}\n".format(exc.message))


def _classify_exit(result: "runner_mod.RunResult") -> ClacmdError:
    stderr = (result.stderr or "").strip()
    low = stderr.lower()
    if any(marker in low for marker in _AUTH_MARKERS):
        return ClacmdError(
            CLAUDE_AUTH_REQUIRED,
            "Claude Code authentication required (run `claude /login`).",
            stderr=stderr[:4000] or None,
            extra={"duration_ms": result.duration_ms},
        )
    return ClacmdError(
        CLAUDE_EXIT_NONZERO,
        "Claude command failed",
        exit_code=_normalize_exit_code(result.returncode),
        stderr=stderr[:4000] or None,
        extra={"duration_ms": result.duration_ms},
    )


def _normalize_exit_code(returncode: Optional[int]) -> int:
    """Map a subprocess return code to a valid (0-255) process exit code.

    Signal deaths arrive as negative codes (e.g. -9 for SIGKILL); convert them
    to the conventional ``128 + signal`` form rather than letting a negative
    value land in the JSON envelope and wrap mod 256 at the OS boundary.
    """
    if returncode is None:
        return 1
    if returncode < 0:
        return 128 + (-returncode)
    return returncode or 1


def _print_dry_run(command: List[str], args) -> int:
    safe = redact_argv(command)
    if args.json:
        _write_stdout(json.dumps({"ok": True, "dry_run": True, "command": safe}, ensure_ascii=False))
    else:
        _write_stdout("DRY RUN — would execute:\n" + " ".join(shlex.quote(a) for a in safe))
    return 0


def _fail(exc: ClacmdError, args, duration_ms: Optional[int]) -> int:
    if args.json:
        _write_stdout(json.dumps(exc.to_envelope(duration_ms), ensure_ascii=False))
        if args.debug and exc.stderr:
            sys.stderr.write(redact(exc.stderr) + "\n")
    else:
        sys.stderr.write("claudecmd: error [{}]: {}\n".format(exc.kind, exc.message))
        if args.debug and exc.stderr:
            sys.stderr.write(redact(exc.stderr) + "\n")
    return exc.exit_code


def _write_stdout(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    sys.stdout.flush()


def entrypoint() -> None:  # pragma: no cover - console_scripts shim
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
