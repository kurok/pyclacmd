"""``claudecmd`` — programmatic, scriptable driver for Claude Code's interactive session.

Spawns the interactive Claude Code TUI (not ``-p``), drives it under a PTY, and
emits the parsed assistant reply (optionally as a JSON envelope). Driving the
interactive session keeps automated calls on the interactive (subscription)
path rather than separately-priced ``-p``/headless usage.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import List, Optional

from . import __version__
from .errors import (
    ClacmdError,
    CLAUDE_AUTH_REQUIRED,
    CWD_NOT_FOUND,
    NO_PROMPT,
    UNKNOWN,
)
from .prompt import DEFAULT_MAX_STDIN_BYTES, cleanup_temp_files, collect_prompt, read_stdin
from .redact import redact, redact_argv
from . import output as output_mod
from . import interactive_runner as ir
from .session_store import SessionStore

# Substrings in the rendered TUI that indicate Claude needs authentication.
_AUTH_MARKERS = (
    "invalid api key",
    "authentication_error",
    "run `claude /login`",
    "please run claude",
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
        description="Programmatic driver for Claude Code's interactive session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", nargs="?", help="Prompt text (or pipe via stdin)")
    parser.add_argument("--json", action="store_true", help="Emit a stable JSON envelope")
    parser.add_argument("--raw", action="store_true", help="Print the full rendered TUI screen (debug)")
    parser.add_argument("--cwd", metavar="PATH", help="Working directory for Claude")
    parser.add_argument("--session", metavar="ID-OR-NAME", help="Resume a session by UUID or local name")
    parser.add_argument("--timeout", type=float, metavar="SECONDS", help="Abort after SECONDS")
    parser.add_argument("--model", help="Model alias or full name")
    parser.add_argument("--tools", dest="tools", metavar="TOOLS", help='Built-in tools to allow (e.g. "Bash,Read"); "" disables all')
    parser.add_argument("--permission-mode", dest="permission_mode", help="Claude permission mode")
    parser.add_argument("--system-prompt", dest="system_prompt", help="Replace the system prompt")
    parser.add_argument("--append-system-prompt", dest="append_system_prompt", help="Append to the system prompt")
    parser.add_argument("--allowed-tools", dest="allowed_tools", help='Permission allow patterns, e.g. "Bash(git:*),Read"')
    parser.add_argument("--disallowed-tools", dest="disallowed_tools", help="Permission deny patterns")
    parser.add_argument("--add-dir", dest="add_dirs", action="append", metavar="PATH", help="Extra allowed directory (repeatable)")
    parser.add_argument("--debug", action="store_true", help="Emit diagnostics to stderr (redacted)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Print the command plan, do not run Claude")
    parser.add_argument("--max-stdin-bytes", type=int, default=DEFAULT_MAX_STDIN_BYTES, dest="max_stdin_bytes", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version="claudecmd {}".format(__version__))
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
            if not args.json:
                parser.print_usage(sys.stderr)
            raise ClacmdError(
                NO_PROMPT,
                "No prompt provided. Pass a prompt argument or pipe data via stdin.",
            )

        prompt, temp_files = collect_prompt(
            args.prompt, stdin_text, max_stdin_bytes=args.max_stdin_bytes, debug=args.debug
        )

        store = SessionStore()
        resume_id = store.resolve(args.session) if args.session else None
        if args.session:
            dbg("session {!r} resolved to {}".format(args.session, resume_id or "(new)"))

        return _run(prompt, args, resume_id, dbg)

    except ClacmdError as exc:
        dbg("error: {} [{}]".format(exc.message, exc.kind))
        return _fail(exc, args, exc.extra.get("duration_ms"))
    except BrokenPipeError:
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


def _run(prompt, args, resume_id, dbg) -> int:
    claude_bin = ir.default_claude_bin()
    argv = ir.build_interactive_argv(
        prompt,
        claude_bin=claude_bin,
        model=args.model,
        permission_mode=args.permission_mode,
        system_prompt=args.system_prompt,
        append_system_prompt=args.append_system_prompt,
        allowed_tools=args.allowed_tools,
        disallowed_tools=args.disallowed_tools,
        tools=args.tools,
        add_dirs=args.add_dirs,
        resume_session_id=resume_id,
    )
    if args.dry_run:
        return _print_dry_run(argv, args)

    dbg("argv: " + " ".join(shlex.quote(a) for a in redact_argv(argv)))
    result = ir.run_interactive(
        prompt,
        claude_bin=claude_bin,
        cwd=args.cwd,
        model=args.model,
        permission_mode=args.permission_mode,
        system_prompt=args.system_prompt,
        append_system_prompt=args.append_system_prompt,
        allowed_tools=args.allowed_tools,
        disallowed_tools=args.disallowed_tools,
        tools=args.tools,
        add_dirs=args.add_dirs,
        resume_session_id=resume_id,
        timeout=args.timeout,
    )
    dbg("events: {} ({}ms)".format(result.events, result.duration_ms))

    if not result.text.strip() and not args.raw:
        low = result.rendered.lower()
        if any(m in low for m in _AUTH_MARKERS):
            raise ClacmdError(
                CLAUDE_AUTH_REQUIRED,
                "Claude Code authentication required (run `claude /login`).",
                extra={"duration_ms": result.duration_ms},
            )
        raise ClacmdError(
            UNKNOWN,
            "Interactive run produced no extractable assistant text "
            "(re-run with --debug --raw to inspect the rendered screen).",
            extra={"duration_ms": result.duration_ms},
        )

    if args.raw:
        _write_stdout(result.rendered)
    elif args.json:
        envelope = output_mod.success_envelope(
            result.text, None, result.duration_ms, None, None
        )
        envelope["mode"] = "interactive"
        _write_stdout(json.dumps(envelope, ensure_ascii=False))
    else:
        _write_stdout(result.text)
    return 0


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
