"""Optional PTY fallback for environments where ``claude -p`` needs a TTY.

This is deliberately isolated and lazy: ``pexpect`` is only imported when a
PTY run is actually requested, so the core CLI has zero hard dependency on
it.  Output is captured and stripped of ANSI / Kitty keyboard escape
sequences (the latter being a known nuisance on macOS Terminal.app).

PTY runs return plain text only — there is no JSON envelope from Claude in
this path, so session id and cost metadata are unavailable.
"""

from __future__ import annotations

import re
import signal
from typing import Any, List, Optional

from .errors import ClacmdError, CLAUDE_NOT_FOUND, CLAUDE_TIMEOUT, PTY_UNAVAILABLE

# General CSI/escape sequences.
_ANSI_RE = re.compile(r"\x1b\[[0-9;:?]*[ -/]*[@-~]")
# Kitty keyboard protocol sequences (ESC [ ... u) — filtered explicitly per
# the macOS Terminal.app compatibility requirement.
_KITTY_RE = re.compile(r"\x1b\[[\d;:]*u")
# Other escape (OSC / single-char) leftovers.
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_OTHER_ESC_RE = re.compile(r"\x1b[@-Z\\-_]")

# Heuristic markers in stderr/messages that suggest a TTY problem and that a
# PTY retry might help.
_TTY_ERROR_MARKERS = (
    "raw mode",
    "not a tty",
    "not a terminal",
    "inappropriate ioctl",
    "stdin is not",
    "requires a terminal",
    "must be run in a terminal",
    "setrawmode",
)


def strip_ansi(text: str) -> str:
    """Remove ANSI / Kitty / OSC escape sequences from captured PTY output."""
    if not text:
        return text
    text = _KITTY_RE.sub("", text)
    text = _OSC_RE.sub("", text)
    text = _ANSI_RE.sub("", text)
    text = _OTHER_ESC_RE.sub("", text)
    return text


def looks_like_tty_error(text: Optional[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(marker in low for marker in _TTY_ERROR_MARKERS)


def _import_pexpect() -> Any:
    try:
        import pexpect  # type: ignore

        return pexpect
    except ImportError:
        raise ClacmdError(
            PTY_UNAVAILABLE,
            "PTY fallback requires the 'pexpect' package "
            "(install with: pip install 'pyclacmd[pty]').",
        )


def run_pty(
    argv: List[str],
    *,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
    pexpect_module: Optional[Any] = None,
) -> str:
    """Spawn ``claude`` inside a PTY and return its cleaned text output.

    ``pexpect_module`` may be injected for testing; otherwise the real
    ``pexpect`` is imported lazily.
    """
    pexpect = pexpect_module or _import_pexpect()

    try:
        child = pexpect.spawn(
            argv[0],
            list(argv[1:]),
            cwd=cwd,
            timeout=timeout,
            encoding="utf-8",
            codec_errors="replace",
        )
    except getattr(pexpect, "ExceptionPexpect", Exception) as exc:
        raise ClacmdError(
            CLAUDE_NOT_FOUND, "Failed to spawn claude under a PTY: {}".format(exc)
        )

    _forward_sigwinch(child)
    captured: List[str] = []
    try:
        child.expect(pexpect.EOF)
        if child.before:
            captured.append(child.before)
    except getattr(pexpect, "TIMEOUT", Exception) as exc:
        _force_close(child)
        raise ClacmdError(
            CLAUDE_TIMEOUT,
            "Claude PTY command timed out after {}s".format(timeout),
            extra={"detail": str(exc)},
        )
    finally:
        _force_close(child)

    return strip_ansi("".join(captured))


def _forward_sigwinch(child: Any) -> None:
    """Best-effort: resize the child PTY when the controlling terminal does."""
    try:
        import termios  # noqa: F401  (presence check)
        import struct
        import fcntl as _fcntl
        import sys

        def _resize(_signum: int, _frame: Any) -> None:  # pragma: no cover
            try:
                packed = _fcntl.ioctl(
                    sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8
                )
                rows, cols, _, _ = struct.unpack("HHHH", packed)
                child.setwinsize(rows, cols)
            except Exception:
                pass

        if hasattr(signal, "SIGWINCH"):
            signal.signal(signal.SIGWINCH, _resize)
    except Exception:
        pass


def _force_close(child: Any) -> None:
    try:
        child.close(force=True)
    except Exception:
        pass
