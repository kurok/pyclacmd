"""Prompt collection: argv + stdin, oversize handling, temp-file fallback.

Prompt source priority:
  1. positional CLI argument
  2. piped STDIN
  3. (neither -> the CLI raises a usage error)

When both a positional prompt and stdin are present they are combined
safely.  When stdin is larger than the configured guard it is written to a
restrictive-permission temp file and the prompt references that file instead
of inlining megabytes of text.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import List, Optional, TextIO, Tuple

from .errors import ClacmdError, NO_PROMPT

# Default guard, kept under Claude Code's documented ~10 MB stdin cap.
DEFAULT_MAX_STDIN_BYTES = 9 * 1024 * 1024

STDIN_SEPARATOR = "--- STDIN ---"


def read_stdin(stream: Optional[TextIO] = None) -> Optional[str]:
    """Read piped stdin, or ``None`` when stdin is an interactive terminal.

    We never block waiting on an interactive TTY: if ``isatty()`` is true we
    treat stdin as absent.  Empty piped input is also treated as absent.
    """
    stream = stream if stream is not None else sys.stdin
    try:
        if stream.isatty():
            return None
    except (ValueError, AttributeError):
        # Closed or unusual stream object: fall through and try to read.
        pass
    try:
        data = stream.read()
    except Exception:
        return None
    if data is None or data == "":
        return None
    return data


def collect_prompt(
    positional: Optional[str],
    stdin_text: Optional[str],
    *,
    max_stdin_bytes: int = DEFAULT_MAX_STDIN_BYTES,
    debug: bool = False,
    tmp_dir: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Build the final prompt string.

    Returns ``(prompt, temp_files)``.  ``temp_files`` lists any temp files
    created for oversize stdin; the caller is responsible for cleanup (unless
    ``debug`` is set, in which case the caller should keep them).
    """
    temp_files: List[str] = []
    pos = positional.strip() if positional else None
    has_pos = bool(pos)
    has_stdin = stdin_text is not None and stdin_text != ""

    if not has_pos and not has_stdin:
        raise ClacmdError(
            NO_PROMPT,
            "No prompt provided. Pass a prompt argument or pipe data via stdin.",
        )

    if has_stdin:
        stdin_bytes = len(stdin_text.encode("utf-8", errors="replace"))
        if stdin_bytes > max_stdin_bytes:
            path = _write_temp(stdin_text, tmp_dir)
            temp_files.append(path)
            reference = (
                "The STDIN input was too large to inline ({} bytes); it was "
                "saved to a file.\nPlease read the content in this file: {}".format(
                    stdin_bytes, path
                )
            )
            if has_pos:
                return "{}\n\n{}".format(pos, reference), temp_files
            return reference, temp_files

    if has_pos and has_stdin:
        prompt = "{}\n\n{}\n{}".format(pos, STDIN_SEPARATOR, stdin_text)
    elif has_pos:
        prompt = pos  # type: ignore[assignment]
    else:
        prompt = stdin_text  # type: ignore[assignment]
    return prompt, temp_files


def _write_temp(text: str, tmp_dir: Optional[str] = None) -> str:
    """Write ``text`` to a 0600 temp file and return its path."""
    fd, path = tempfile.mkstemp(prefix="claudecmd-input-", suffix=".txt", dir=tmp_dir)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def cleanup_temp_files(paths: List[str]) -> None:
    """Remove temp files, ignoring already-gone / permission errors."""
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass
