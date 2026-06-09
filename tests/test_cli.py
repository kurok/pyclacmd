from __future__ import annotations

import json
import os
import re

import pytest

from claudecmd import cli
from claudecmd.cli import main
from claudecmd.errors import (
    ClacmdError,
    CLAUDE_AUTH_REQUIRED,
    CLAUDE_NOT_FOUND,
    CLAUDE_TIMEOUT,
    SESSION_STORE_ERROR,
)
from claudecmd.interactive_runner import InteractiveResult
from claudecmd.session_store import SessionStore

UUID = "11111111-1111-1111-1111-111111111111"


class _Recorder:
    """Stand-in for run_interactive that records calls and returns canned output."""

    def __init__(self, text="hello world", rendered=None, duration_ms=42):
        self.text = text
        self.rendered = rendered
        self.duration_ms = duration_ms
        self.calls = []

    def __call__(self, prompt, **kw):
        self.calls.append(dict(prompt=prompt, **kw))
        rendered = self.rendered
        if rendered is None:
            rendered = "❯ {}\n⏺ {}\n".format(prompt, self.text)
        return InteractiveResult(
            text=self.text, rendered=rendered, duration_ms=self.duration_ms, events=["complete"]
        )


@pytest.fixture
def fake_interactive(monkeypatch):
    def _install(text="hello world", rendered=None, duration_ms=42):
        rec = _Recorder(text=text, rendered=rendered, duration_ms=duration_ms)
        monkeypatch.setattr(cli.ir, "run_interactive", rec)
        return rec

    return _install


@pytest.fixture
def raise_interactive(monkeypatch):
    def _install(exc):
        def _raise(*a, **k):
            raise exc

        monkeypatch.setattr(cli.ir, "run_interactive", _raise)

    return _install


# --- prompt collection ------------------------------------------------------
def test_default_prints_only_result(fake_interactive, set_stdin, capsys):
    fake_interactive(text="hello world")
    set_stdin("")
    rc = main(["say hi"])
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "hello world\n"
    assert out.err == ""


def test_reads_prompt_from_argv(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("")
    main(["my prompt here"])
    assert rec.calls[0]["prompt"] == "my prompt here"


def test_reads_prompt_from_stdin(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("piped prompt")
    main([])
    assert rec.calls[0]["prompt"] == "piped prompt"


def test_combines_argv_and_stdin(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("the diff body")
    main(["review this"])
    prompt = rec.calls[0]["prompt"]
    assert "review this" in prompt
    assert "--- STDIN ---" in prompt
    assert "the diff body" in prompt


# --- empty prompt -----------------------------------------------------------
def test_rejects_empty_prompt(set_stdin, capsys):
    set_stdin("")
    rc = main([])
    err = capsys.readouterr().err
    assert rc == 64  # no_prompt
    assert "no_prompt" in err


def test_no_prompt_json_envelope(set_stdin, capsys):
    set_stdin("")
    rc = main(["--json"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 64
    assert env["ok"] is False
    assert env["kind"] == "no_prompt"


# --- output formatting ------------------------------------------------------
def test_json_envelope(fake_interactive, set_stdin, capsys):
    fake_interactive(text="hello world", duration_ms=99)
    set_stdin("")
    rc = main(["--json", "hi"])
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["result"] == "hello world"
    assert env["mode"] == "interactive"
    assert env["session_id"] is None
    assert env["cost_usd"] is None
    assert env["duration_ms"] == 99


def test_raw_prints_rendered_screen(fake_interactive, set_stdin, capsys):
    fake_interactive(text="hi", rendered="FULL SCREEN HERE\n❯\n")
    set_stdin("")
    rc = main(["--raw", "hi"])
    assert rc == 0
    assert "FULL SCREEN HERE" in capsys.readouterr().out


# --- passthrough options ----------------------------------------------------
def test_passes_model_and_tools(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("")
    main(["--model", "haiku", "--tools", "", "hi"])
    assert rec.calls[0]["model"] == "haiku"
    assert rec.calls[0]["tools"] == ""


def test_passes_cwd(fake_interactive, set_stdin, tmp_path):
    rec = fake_interactive()
    work = tmp_path / "work"
    work.mkdir()
    set_stdin("")
    main(["--cwd", str(work), "where"])
    assert rec.calls[0]["cwd"] == str(work)


def test_uuid_session_passed_as_resume(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("")
    main(["--session", UUID, "hi"])
    assert rec.calls[0]["resume_session_id"] == UUID


# --- error paths ------------------------------------------------------------
def test_cwd_not_found(set_stdin, capsys):
    set_stdin("")
    rc = main(["--cwd", "/no/such/directory/here", "hi"])
    assert rc == 66
    assert "cwd_not_found" in capsys.readouterr().err


def test_timeout_surfaces(raise_interactive, set_stdin, capsys):
    raise_interactive(ClacmdError(CLAUDE_TIMEOUT, "Interactive run exceeded 0s"))
    set_stdin("")
    rc = main(["--timeout", "0.3", "hi"])
    assert rc == 124
    assert "claude_timeout" in capsys.readouterr().err


def test_claude_not_found(raise_interactive, set_stdin, capsys):
    raise_interactive(ClacmdError(CLAUDE_NOT_FOUND, "no claude"))
    set_stdin("")
    rc = main(["hi"])
    assert rc == 127
    assert "claude_not_found" in capsys.readouterr().err


def test_auth_required_detected_from_screen(fake_interactive, set_stdin, capsys):
    # Empty extraction + an auth marker in the rendered screen -> auth error.
    fake_interactive(text="", rendered="Invalid API key. Please run `claude /login`\n")
    set_stdin("")
    rc = main(["--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert env["kind"] == "claude_auth_required"


def test_empty_text_is_unknown_error(fake_interactive, set_stdin, capsys):
    fake_interactive(text="", rendered="a screen with no reply and no auth marker")
    set_stdin("")
    rc = main(["hi"])
    assert rc == 1
    assert "unknown" in capsys.readouterr().err


def test_session_store_error_surfaces(set_stdin, capsys, monkeypatch):
    def boom(self, name_or_id):
        raise ClacmdError(SESSION_STORE_ERROR, "disk on fire")

    monkeypatch.setattr(SessionStore, "resolve", boom)
    set_stdin("")
    rc = main(["--session", "whatever", "hi"])
    assert rc == 74
    assert "session_store_error" in capsys.readouterr().err


# --- dry run ----------------------------------------------------------------
def test_dry_run_shows_interactive_argv(set_stdin, capsys):
    set_stdin("")
    rc = main(["--dry-run", "hi there"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out
    assert "hi there" in out
    assert "-p" not in out  # interactive: never the print flag


def test_dry_run_json(set_stdin, capsys):
    set_stdin("")
    main(["--dry-run", "--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["dry_run"] is True
    assert "hi" in env["command"]
    assert "-p" not in env["command"]


def test_dry_run_redacts_secrets(set_stdin, capsys):
    set_stdin("")
    main(["--dry-run", "use API_KEY=topsecretvalue now"])
    out = capsys.readouterr().out
    assert "topsecretvalue" not in out
    assert "***REDACTED***" in out


# --- oversize stdin (temp-file spill) ---------------------------------------
def test_oversize_stdin_writes_and_cleans_temp_file(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("z" * 5000)
    rc = main(["--max-stdin-bytes", "100", "do the thing"])
    assert rc == 0
    prompt = rec.calls[0]["prompt"]
    match = re.search(r"this file: (\S+)", prompt)
    assert match, prompt
    temp_path = match.group(1)
    assert "z" * 5000 not in prompt
    assert not os.path.exists(temp_path)  # cleaned (no --debug)


def test_oversize_stdin_debug_keeps_temp_file(fake_interactive, set_stdin):
    rec = fake_interactive()
    set_stdin("y" * 5000)
    main(["--max-stdin-bytes", "100", "--debug", "keep it"])
    prompt = rec.calls[0]["prompt"]
    match = re.search(r"this file: (\S+)", prompt)
    assert match
    temp_path = match.group(1)
    try:
        assert os.path.exists(temp_path)  # kept for inspection under --debug
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
