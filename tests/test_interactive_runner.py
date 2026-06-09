from __future__ import annotations

import pytest

from claudecmd import interactive_runner as ir
from claudecmd.interactive_runner import (
    build_interactive_argv,
    extract_response,
    _is_rule,
    _is_status,
)

RULE = "─" * 40


# --- extract_response -------------------------------------------------------
def test_extract_simple_reply():
    screen = [
        "❯ say hi",
        "",
        "⏺ Hello there!",
        "",
        "✻ Churned for 1s",
        RULE,
        "❯",
        RULE,
        "  chat:1k / 200k",
    ]
    assert extract_response(screen, "say hi") == "Hello there!"


def test_extract_multiline_with_list_and_status():
    screen = [
        "❯ list three fruits",
        "",
        "⏺ Here are three:",
        "",
        "  - Apple",
        "  - Banana",
        "  - Cherry",
        "",
        "✻ Baked for 2s",
        RULE,
        "❯",
        RULE,
        "  chat:5k / 200k  Sonnet",
    ]
    assert extract_response(screen, "list three fruits") == (
        "Here are three:\n\n- Apple\n- Banana\n- Cherry"
    )


def test_extract_picks_last_turn():
    screen = [
        "❯ first question",
        "⏺ first answer",
        RULE,
        "❯ second question",
        "⏺ second answer",
        RULE,
        "❯",
        RULE,
        "  chat:9k / 200k",
    ]
    assert extract_response(screen, "second question") == "second answer"


def test_is_rule_and_status():
    assert _is_rule(RULE)
    assert _is_rule("━" * 12)
    assert not _is_rule("just text")
    assert _is_status("✻ Churned for 3s")
    assert not _is_status("⏺ a real reply")


# --- build_interactive_argv -------------------------------------------------
def test_argv_prompt_is_first_and_no_print_flag():
    argv = build_interactive_argv("hello world", claude_bin="claude")
    assert argv[0] == "claude"
    assert argv[1] == "hello world"  # prompt FIRST
    assert "-p" not in argv and "--print" not in argv


def test_argv_variadic_tools_placed_last():
    argv = build_interactive_argv(
        "do a thing", claude_bin="claude", tools="", model="haiku"
    )
    # prompt must not be the final token (else --tools would have eaten it)
    assert argv[1] == "do a thing"
    assert argv[-2:] == ["--tools", ""]
    assert argv.index("--model") < argv.index("--tools")


def test_argv_resume_and_permission():
    argv = build_interactive_argv(
        "p", claude_bin="claude", permission_mode="plan", resume_session_id="abc-123"
    )
    assert "--resume" in argv and argv[argv.index("--resume") + 1] == "abc-123"
    assert "--permission-mode" in argv


# --- run_interactive (fully mocked pexpect + pyte) --------------------------
class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, d=1.0):
        self.t += d


class _FakeScreen:
    def __init__(self, cols, rows):
        self.display = []


class _FakeByteStream:
    def __init__(self, screen):
        self.screen = screen

    def feed(self, chunk):
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        self.screen.display = text.split("\n")


class _FakePyte:
    Screen = _FakeScreen
    ByteStream = _FakeByteStream


class _EOF(Exception):
    pass


class _TIMEOUT(Exception):
    pass


class _ExceptionPexpect(Exception):
    pass


class _FakeChild:
    def __init__(self, script, clock):
        self.script = list(script)
        self.i = 0
        self.clock = clock
        self.sends = []
        self.closed = False

    def read_nonblocking(self, size=0, timeout=0):
        self.clock.tick(1.0)
        if self.i < len(self.script):
            item = self.script[self.i]
            self.i += 1
            if item == "TIMEOUT":
                raise _TIMEOUT()
            if item == "EOF":
                raise _EOF()
            return item.encode()
        raise _TIMEOUT()

    def send(self, s):
        self.sends.append(s)

    def close(self, force=False):
        self.closed = True


class _FakePexpect:
    EOF = _EOF
    TIMEOUT = _TIMEOUT
    ExceptionPexpect = _ExceptionPexpect

    def __init__(self, child):
        self.child = child
        self.spawn_args = None

    def spawn(self, cmd, args, cwd=None, encoding=None, timeout=None, dimensions=None):
        self.spawn_args = {"cmd": cmd, "args": args, "cwd": cwd}
        return self.child


def test_run_interactive_handles_trust_and_extracts(monkeypatch):
    monkeypatch.setattr(ir.time, "sleep", lambda *_a, **_k: None)

    trust = (
        "Quick safety check: Is this a project you trust?\n"
        "  ❯ 1. Yes, I trust this folder\n    2. No, exit\n"
    )
    reply = "\n".join(
        ["❯ say hi", "", "⏺ Hello there!", "", RULE, "❯", RULE, "  chat:1k / 200k"]
    )
    script = [trust, reply, "TIMEOUT", "TIMEOUT", "TIMEOUT", "TIMEOUT", "TIMEOUT"]

    clock = _Clock()
    child = _FakeChild(script, clock)
    fake_pexpect = _FakePexpect(child)

    result = ir.run_interactive(
        "say hi",
        claude_bin="claude",
        cwd="/tmp",
        pexpect_module=fake_pexpect,
        pyte_module=_FakePyte,
        _clock=clock,
    )

    assert result.text == "Hello there!"
    assert "answered_trust" in result.events
    assert "complete" in result.events
    assert "\r" in child.sends  # accepted the trust dialog
    assert child.closed is True
    # prompt was passed first, no -p
    assert fake_pexpect.spawn_args["args"][0] == "say hi"
    assert "-p" not in fake_pexpect.spawn_args["args"]


def test_run_interactive_pty_unavailable_without_pyte(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pyte", None)
    with pytest.raises(Exception) as exc:
        ir.run_interactive("hi", claude_bin="claude", pexpect_module=_FakePexpect(_FakeChild([], _Clock())))
    assert "pyte" in str(exc.value).lower()
