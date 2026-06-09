"""Structured error taxonomy and exit-code mapping for claudecmd.

Every failure path raises :class:`ClacmdError` carrying a stable ``kind``
string (one of the constants below), a human message, and a process exit
code.  The CLI turns these into stderr messages (default mode) or a JSON
error envelope (``--json`` mode).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .redact import redact

# --- Error kinds (stable, documented strings) -------------------------------
CLAUDE_NOT_FOUND = "claude_not_found"
CLAUDE_AUTH_REQUIRED = "claude_auth_required"
CLAUDE_EXIT_NONZERO = "claude_exit_nonzero"
CLAUDE_TIMEOUT = "claude_timeout"
INVALID_JSON = "invalid_json"
STDIN_TOO_LARGE = "stdin_too_large"
CWD_NOT_FOUND = "cwd_not_found"
SESSION_STORE_ERROR = "session_store_error"
PTY_UNAVAILABLE = "pty_unavailable"
NO_PROMPT = "no_prompt"
UNKNOWN = "unknown"

ALL_KINDS = (
    CLAUDE_NOT_FOUND,
    CLAUDE_AUTH_REQUIRED,
    CLAUDE_EXIT_NONZERO,
    CLAUDE_TIMEOUT,
    INVALID_JSON,
    STDIN_TOO_LARGE,
    CWD_NOT_FOUND,
    SESSION_STORE_ERROR,
    PTY_UNAVAILABLE,
    NO_PROMPT,
    UNKNOWN,
)

# Default process exit codes per kind.  ``claude_exit_nonzero`` is special:
# the CLI passes through Claude's own exit code when it can.
EXIT_CODES: Dict[str, int] = {
    CLAUDE_NOT_FOUND: 127,
    CLAUDE_AUTH_REQUIRED: 2,
    CLAUDE_EXIT_NONZERO: 1,
    CLAUDE_TIMEOUT: 124,
    INVALID_JSON: 65,
    STDIN_TOO_LARGE: 64,
    CWD_NOT_FOUND: 66,
    SESSION_STORE_ERROR: 74,
    PTY_UNAVAILABLE: 69,
    NO_PROMPT: 64,
    UNKNOWN: 1,
}


class ClacmdError(Exception):
    """A structured, classifiable claudecmd failure."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        exit_code: Optional[int] = None,
        stderr: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.exit_code = exit_code if exit_code is not None else EXIT_CODES.get(kind, 1)
        self.stderr = stderr
        self.extra: Dict[str, Any] = dict(extra or {})

    def to_envelope(self, duration_ms: Optional[int] = None) -> Dict[str, Any]:
        """Build the stable ``--json`` failure envelope.

        Only the documented fields are emitted (``ok``, ``error``, ``kind``,
        ``exit_code``, ``stderr``, ``duration_ms``) — arbitrary ``extra`` keys
        are intentionally *not* splatted in, so raw model/process output never
        leaks through this channel. The ``stderr`` field is redacted.
        """
        env: Dict[str, Any] = {
            "ok": False,
            "error": self.message,
            "kind": self.kind,
            "exit_code": self.exit_code,
        }
        if self.stderr is not None:
            env["stderr"] = redact(self.stderr)
        # duration may be carried in extra or passed explicitly.
        dur = duration_ms if duration_ms is not None else self.extra.get("duration_ms")
        if dur is not None:
            env["duration_ms"] = dur
        return env

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "ClacmdError(kind={!r}, message={!r}, exit_code={!r})".format(
            self.kind, self.message, self.exit_code
        )
