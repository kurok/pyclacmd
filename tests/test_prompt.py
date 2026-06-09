from __future__ import annotations

import os

import pytest

from claudecmd.errors import ClacmdError, NO_PROMPT
from claudecmd.prompt import (
    STDIN_SEPARATOR,
    cleanup_temp_files,
    collect_prompt,
    read_stdin,
)


def test_positional_only():
    prompt, temps = collect_prompt("review this diff", None)
    assert prompt == "review this diff"
    assert temps == []


def test_stdin_only():
    prompt, temps = collect_prompt(None, "piped content")
    assert prompt == "piped content"
    assert temps == []


def test_combines_positional_and_stdin():
    prompt, temps = collect_prompt("Review this diff", "diff body here")
    assert "Review this diff" in prompt
    assert STDIN_SEPARATOR in prompt
    assert "diff body here" in prompt
    assert prompt.index("Review this diff") < prompt.index(STDIN_SEPARATOR)


def test_rejects_empty_prompt():
    with pytest.raises(ClacmdError) as exc:
        collect_prompt(None, None)
    assert exc.value.kind == NO_PROMPT


def test_whitespace_only_positional_is_empty():
    with pytest.raises(ClacmdError):
        collect_prompt("   \n  ", None)


def test_oversized_stdin_writes_temp_file(tmp_path):
    big = "x" * 5000
    prompt, temps = collect_prompt(None, big, max_stdin_bytes=1000, tmp_dir=str(tmp_path))
    assert len(temps) == 1
    path = temps[0]
    assert os.path.exists(path)
    assert "this file" in prompt
    assert path in prompt
    # restrictive perms
    assert (os.stat(path).st_mode & 0o777) == 0o600
    with open(path) as handle:
        assert handle.read() == big
    cleanup_temp_files(temps)
    assert not os.path.exists(path)


def test_oversized_stdin_keeps_positional(tmp_path):
    prompt, temps = collect_prompt(
        "do the thing", "y" * 5000, max_stdin_bytes=10, tmp_dir=str(tmp_path)
    )
    assert prompt.startswith("do the thing")
    assert temps and os.path.exists(temps[0])
    cleanup_temp_files(temps)


def test_read_stdin_returns_none_for_tty():
    class FakeTTY:
        def isatty(self):
            return True

        def read(self):  # pragma: no cover - should not be called
            raise AssertionError("must not read a tty")

    assert read_stdin(FakeTTY()) is None


def test_read_stdin_empty_is_none():
    import io

    assert read_stdin(io.StringIO("")) is None
    assert read_stdin(io.StringIO("data")) == "data"
