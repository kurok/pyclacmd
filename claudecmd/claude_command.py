"""Build the ``claude`` argument vector from normalized claudecmd options.

This module is pure: it turns a :class:`ClaudeOptions` plus a prompt and an
output format into a subprocess argv list.  No shell strings are ever built,
so user input cannot be interpreted by a shell.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

# Valid Claude Code ``--output-format`` values we support.
OUTPUT_JSON = "json"
OUTPUT_STREAM_JSON = "stream-json"
OUTPUT_TEXT = "text"


def default_claude_bin() -> str:
    """The ``claude`` executable to invoke (override via env for tests)."""
    return os.environ.get("CLAUDECMD_CLAUDE_BIN") or "claude"


@dataclass
class ClaudeOptions:
    """Normalized pass-through options destined for the ``claude`` CLI."""

    model: Optional[str] = None
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None
    allowed_tools: Optional[str] = None
    disallowed_tools: Optional[str] = None
    permission_mode: Optional[str] = None
    no_session_persistence: bool = False
    # Resolved UUID to resume (set by the session layer), if any.
    resume_session_id: Optional[str] = None
    cwd: Optional[str] = None


def build_command(
    prompt: str,
    options: ClaudeOptions,
    *,
    output_format: str = OUTPUT_JSON,
    claude_bin: Optional[str] = None,
) -> List[str]:
    """Return the argv list for invoking Claude Code in print mode.

    Public claudecmd flag names are normalized to Claude Code's expected
    spellings here (e.g. ``--allowed-tools`` -> ``--allowedTools``).
    """
    binary = claude_bin or default_claude_bin()
    argv: List[str] = [binary, "-p", prompt, "--output-format", output_format]

    # stream-json in print mode requires --verbose in current Claude Code.
    if output_format == OUTPUT_STREAM_JSON:
        argv.append("--verbose")

    opt = options
    if opt.model:
        argv += ["--model", opt.model]
    if opt.max_turns is not None:
        # Note: not all Claude Code builds expose --max-turns; forwarded as-is.
        argv += ["--max-turns", str(opt.max_turns)]
    if opt.max_budget_usd is not None:
        argv += ["--max-budget-usd", _format_number(opt.max_budget_usd)]
    if opt.system_prompt is not None:
        argv += ["--system-prompt", opt.system_prompt]
    if opt.append_system_prompt is not None:
        argv += ["--append-system-prompt", opt.append_system_prompt]
    if opt.allowed_tools:
        argv += ["--allowedTools", opt.allowed_tools]
    if opt.disallowed_tools:
        argv += ["--disallowedTools", opt.disallowed_tools]
    if opt.permission_mode:
        argv += ["--permission-mode", opt.permission_mode]
    if opt.no_session_persistence:
        argv += ["--no-session-persistence"]
    if opt.resume_session_id:
        argv += ["--resume", opt.resume_session_id]

    return argv


def _format_number(value: float) -> str:
    """Render a budget number without a trailing ``.0`` for whole values."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
