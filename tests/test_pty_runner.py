from __future__ import annotations

import sys

import pytest

from claudecmd import pty_runner
from claudecmd.errors import ClacmdError, CLAUDE_TIMEOUT, PTY_UNAVAILABLE


def test_strip_ansi_removes_color_codes():
    text = "\x1b[31mred\x1b[0m text"
    assert pty_runner.strip_ansi(text) == "red text"


def test_strip_ansi_removes_kitty_keyboard_sequences():
    # Kitty keyboard protocol: ESC [ ... u
    text = "before\x1b[1;2uafter\x1b[57344u!"
    assert pty_runner.strip_ansi(text) == "beforeafter!"


def test_looks_like_tty_error():
    assert pty_runner.looks_like_tty_error("Error: stdin is not a TTY")
    assert pty_runner.looks_like_tty_error("Raw mode is not supported")
    assert not pty_runner.looks_like_tty_error("some unrelated failure")
    assert not pty_runner.looks_like_tty_error(None)


# --- a minimal fake pexpect -------------------------------------------------
class _FakeEOF(Exception):
    pass


class _FakeTIMEOUT(Exception):
    pass


class _FakeExceptionPexpect(Exception):
    pass


class _FakeChild:
    def __init__(self, before, raise_timeout=False):
        self.before = before
        self._raise_timeout = raise_timeout
        self.closed = False

    def expect(self, _pattern):
        if self._raise_timeout:
            raise _FakeTIMEOUT("timed out")
        return 0

    def setwinsize(self, _rows, _cols):  # pragma: no cover - signal path
        pass

    def close(self, force=False):
        self.closed = True


class _FakePexpect:
    EOF = _FakeEOF
    TIMEOUT = _FakeTIMEOUT
    ExceptionPexpect = _FakeExceptionPexpect

    def __init__(self, before="output", raise_timeout=False):
        self._before = before
        self._raise_timeout = raise_timeout
        self.spawn_args = None
        self.child = None

    def spawn(self, command, args, cwd=None, timeout=None, encoding=None, codec_errors=None):
        self.spawn_args = {
            "command": command,
            "args": args,
            "cwd": cwd,
            "timeout": timeout,
        }
        self.child = _FakeChild(self._before, self._raise_timeout)
        return self.child


def test_run_pty_returns_cleaned_output():
    fake = _FakePexpect(before="\x1b[32mhello from pty\x1b[0m")
    out = pty_runner.run_pty(
        ["claude", "-p", "hi", "--output-format", "text"],
        cwd="/tmp",
        timeout=5,
        pexpect_module=fake,
    )
    assert out == "hello from pty"
    assert fake.spawn_args["command"] == "claude"
    assert fake.spawn_args["args"] == ["-p", "hi", "--output-format", "text"]
    assert fake.spawn_args["cwd"] == "/tmp"
    assert fake.child.closed is True


def test_run_pty_timeout():
    fake = _FakePexpect(raise_timeout=True)
    with pytest.raises(ClacmdError) as exc:
        pty_runner.run_pty(["claude", "-p", "hi"], timeout=1, pexpect_module=fake)
    assert exc.value.kind == CLAUDE_TIMEOUT


def test_pty_unavailable_when_pexpect_missing(monkeypatch):
    # Simulate an un-importable pexpect.
    monkeypatch.setitem(sys.modules, "pexpect", None)
    with pytest.raises(ClacmdError) as exc:
        pty_runner.run_pty(["claude", "-p", "hi"])
    assert exc.value.kind == PTY_UNAVAILABLE
