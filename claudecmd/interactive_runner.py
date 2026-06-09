"""Drive Claude Code's *interactive* session programmatically.

This spawns the full interactive TUI under a pseudo-terminal, renders it with a
real terminal emulator (``pyte``) so layout/whitespace survive, answers the
one-time workspace-trust dialog, waits for the turn to finish, and extracts the
assistant's reply from the rendered screen.

Why: Claude Code prices ``-p``/headless usage separately from interactive
sessions. Driving the interactive session keeps automated calls on the
interactive (subscription) path.

This is best-effort screen-scraping of a human-facing TUI: it is inherently
fragile and exposes no session id / cost metadata. Extraction is heuristic and
tuned to Claude Code's current rendering (v2.1.x).

``pexpect`` and ``pyte`` are required dependencies; they are imported lazily so
import errors surface as a clean :class:`ClacmdError`.
"""

from __future__ import annotations

import os
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .errors import (
    ClacmdError,
    CLAUDE_NOT_FOUND,
    CLAUDE_TIMEOUT,
    PTY_UNAVAILABLE,
)

# --- TUI glyph markers (Claude Code v2.1.x) ---------------------------------
USER_MARK = "❯"        # ❯  user prompt / idle input box
ASSISTANT_MARK = "⏺"   # ⏺  assistant message bullet
# Status / spinner glyphs that lead transient "working"/"done" lines.
STATUS_MARKS = ("✻", "✶", "✽", "✷", "✸", "✳")
# Substring shown while a turn is still generating.
WORKING_MARKER = "esc to interrupt"
TRUST_MARKER = "trust this folder"

# Defaults
DEFAULT_QUIET_PERIOD = 2.5     # seconds of no output that signal turn-complete
DEFAULT_HARD_CAP = 180.0       # absolute ceiling if no explicit timeout
PTY_ROWS, PTY_COLS = 600, 160  # tall virtual screen so long replies don't scroll off


def default_claude_bin() -> str:
    """The ``claude`` executable to invoke (override via env for tests)."""
    return os.environ.get("CLAUDECMD_CLAUDE_BIN") or "claude"


@dataclass
class InteractiveResult:
    text: str
    rendered: str = ""
    duration_ms: Optional[int] = None
    events: List[str] = field(default_factory=list)


def _imports(pexpect_module: Any, pyte_module: Any):
    try:
        pexpect = pexpect_module or __import__("pexpect")
    except ImportError:
        raise ClacmdError(
            PTY_UNAVAILABLE,
            "Interactive mode requires the 'pexpect' package "
            "(install with: pip install pyclacmd).",
        )
    try:
        pyte = pyte_module or __import__("pyte")
    except ImportError:
        raise ClacmdError(
            PTY_UNAVAILABLE,
            "Interactive mode requires the 'pyte' package "
            "(install with: pip install pyclacmd).",
        )
    return pexpect, pyte


def _is_rule(s: str) -> bool:
    """A horizontal box rule (the input-box delimiter)."""
    st = s.strip()
    return len(st) >= 8 and set(st) <= {"─", "━", "-", "—"}


def _is_status(st: str) -> bool:
    return any(st.startswith(m) for m in STATUS_MARKS)


def extract_response(display_lines: List[str], prompt: str) -> str:
    """Pull the assistant's reply out of the rendered TUI screen.

    Heuristic, matched to Claude Code's current layout:
      * find the user-prompt echo line (starts with ❯ and contains the prompt),
      * take everything below it until the bottom input box / footer,
      * drop ✻ status lines, strip the ⏺ bullet, and dedent.
    """
    lines = [l.rstrip() for l in display_lines]
    needle = " ".join(prompt.split())[:24]

    echo_idx = None
    for i, l in enumerate(lines):
        st = l.lstrip()
        if st.startswith(USER_MARK) and needle and needle[:12] in " ".join(l.split()):
            echo_idx = i  # last matching echo = this turn
    if echo_idx is None:
        # Fallback: start just above the first assistant bullet.
        for i, l in enumerate(lines):
            if l.lstrip().startswith(ASSISTANT_MARK):
                echo_idx = i - 1
                break
    if echo_idx is None:
        return ""

    # The reply begins at the first ⏺ bullet after the prompt echo. Starting
    # there skips any continuation lines of a multi-line prompt (e.g. the
    # "--- STDIN ---" block) that the TUI echoes as part of the user turn.
    resp_start = echo_idx + 1
    for j in range(echo_idx + 1, len(lines)):
        if lines[j].lstrip().startswith(ASSISTANT_MARK):
            resp_start = j
            break

    body: List[str] = []
    for l in lines[resp_start:]:
        st = l.strip()
        if _is_rule(st):
            break  # reached the bottom input box
        if st == USER_MARK or "200k" in st or "for shortcuts" in st:
            break  # idle prompt / footer
        body.append(l)

    cleaned: List[str] = []
    for l in body:
        st = l.lstrip()
        if _is_status(st) or WORKING_MARKER in st.lower():
            continue
        if st.startswith(ASSISTANT_MARK):
            idx = l.index(ASSISTANT_MARK)
            l = l[:idx] + " " + l[idx + len(ASSISTANT_MARK):]  # bullet -> space, keep columns
        cleaned.append(l)

    return textwrap.dedent("\n".join(cleaned)).strip("\n").rstrip()


def build_interactive_argv(
    prompt: str,
    *,
    claude_bin: str,
    model: Optional[str] = None,
    permission_mode: Optional[str] = None,
    system_prompt: Optional[str] = None,
    append_system_prompt: Optional[str] = None,
    allowed_tools: Optional[str] = None,
    disallowed_tools: Optional[str] = None,
    tools: Optional[str] = None,
    add_dirs: Optional[List[str]] = None,
    resume_session_id: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """argv for an *interactive* claude run (note: no ``-p``).

    The positional prompt is placed FIRST, immediately after the binary.
    Several claude options are variadic (``--tools <tools...>``,
    ``--allowedTools <tools...>``, ``--add-dir <dirs...>``); if the prompt
    followed them it would be swallowed as one of their values. Prompt-first
    makes that impossible, and the variadic flags are kept last.
    """
    argv: List[str] = [claude_bin, prompt]  # positional prompt: auto-submitted
    if resume_session_id:
        argv += ["--resume", resume_session_id]
    if model:
        argv += ["--model", model]
    if permission_mode:
        argv += ["--permission-mode", permission_mode]
    if system_prompt is not None:
        argv += ["--system-prompt", system_prompt]
    if append_system_prompt is not None:
        argv += ["--append-system-prompt", append_system_prompt]
    for d in add_dirs or []:
        argv += ["--add-dir", d]
    argv += list(extra_args or [])
    # Variadic options last so they can't eat following args:
    if allowed_tools:
        argv += ["--allowedTools", allowed_tools]
    if disallowed_tools:
        argv += ["--disallowedTools", disallowed_tools]
    if tools is not None:
        argv += ["--tools", tools]
    return argv


def run_interactive(
    prompt: str,
    *,
    claude_bin: str,
    cwd: Optional[str] = None,
    model: Optional[str] = None,
    permission_mode: Optional[str] = None,
    system_prompt: Optional[str] = None,
    append_system_prompt: Optional[str] = None,
    allowed_tools: Optional[str] = None,
    disallowed_tools: Optional[str] = None,
    tools: Optional[str] = None,
    add_dirs: Optional[List[str]] = None,
    resume_session_id: Optional[str] = None,
    timeout: Optional[float] = None,
    quiet_period: float = DEFAULT_QUIET_PERIOD,
    extra_args: Optional[List[str]] = None,
    pexpect_module: Any = None,
    pyte_module: Any = None,
    _clock: Any = time.time,
) -> InteractiveResult:
    pexpect, pyte = _imports(pexpect_module, pyte_module)

    argv = build_interactive_argv(
        prompt,
        claude_bin=claude_bin,
        model=model,
        permission_mode=permission_mode,
        system_prompt=system_prompt,
        append_system_prompt=append_system_prompt,
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
        tools=tools,
        add_dirs=add_dirs,
        resume_session_id=resume_session_id,
        extra_args=extra_args,
    )

    screen = pyte.Screen(PTY_COLS, PTY_ROWS)
    stream = pyte.ByteStream(screen)
    hard_cap = timeout if timeout else DEFAULT_HARD_CAP

    try:
        child = pexpect.spawn(
            argv[0], argv[1:], cwd=cwd, encoding=None,
            timeout=5, dimensions=(PTY_ROWS, PTY_COLS),
        )
    except getattr(pexpect, "ExceptionPexpect", Exception) as exc:
        raise ClacmdError(
            CLAUDE_NOT_FOUND, "Failed to spawn claude under a PTY: {}".format(exc)
        )

    events: List[str] = []
    start = last = _clock()
    trusted = False
    saw_assistant = False

    def rendered() -> str:
        return "\n".join(screen.display)

    try:
        while True:
            now = _clock()
            if now - start > hard_cap:
                events.append("hard_cap")
                _interrupt(child)
                raise ClacmdError(
                    CLAUDE_TIMEOUT,
                    "Interactive run exceeded {:.0f}s".format(hard_cap),
                    extra={"duration_ms": int((now - start) * 1000)},
                )
            try:
                chunk = child.read_nonblocking(size=8192, timeout=1)
            except getattr(pexpect, "TIMEOUT", Exception):
                chunk = b""
            except getattr(pexpect, "EOF", Exception):
                events.append("eof")
                break

            if chunk:
                stream.feed(chunk)
                last = _clock()
                low = rendered().lower()
                if not trusted and TRUST_MARKER in low:
                    time.sleep(0.4)
                    child.send("\r")  # accept default "Yes, I trust this folder"
                    trusted = True
                    events.append("answered_trust")
                if ASSISTANT_MARK in rendered():
                    saw_assistant = True
                continue

            # no output this tick
            low = rendered().lower()
            working = WORKING_MARKER in low
            quiet = _clock() - last
            ready = trusted or (_clock() - start) > 5
            if ready and not working and quiet > quiet_period and saw_assistant:
                events.append("complete")
                break
    finally:
        _interrupt(child)

    text = extract_response(screen.display, prompt)
    return InteractiveResult(
        text=text,
        rendered=rendered(),
        duration_ms=int((_clock() - start) * 1000),
        events=events,
    )


def _interrupt(child: Any) -> None:
    try:
        child.send("\x03")
        time.sleep(0.2)
        child.send("\x03")
        time.sleep(0.2)
    except Exception:
        pass
    try:
        child.close(force=True)
    except Exception:
        pass
