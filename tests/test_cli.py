from __future__ import annotations

import json
import os
import re

import pytest

from claudecmd import cli
from claudecmd.cli import main
from claudecmd.errors import ClacmdError, SESSION_STORE_ERROR
from claudecmd.session_store import SessionStore
from tests.conftest import ECHO_BODY, SUCCESS_BODY

UUID = "11111111-1111-1111-1111-111111111111"

STREAM_BODY = r"""
print(json.dumps({"type": "system", "subtype": "init", "session_id": "sess-stream-1"}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello "}]}}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "world"}]}}), flush=True)
print(json.dumps({"type": "result", "subtype": "success", "result": "Hello world",
                  "session_id": "sess-stream-1", "total_cost_usd": 0.01}), flush=True)
"""


def test_default_mode_prints_only_result(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    rc = main(["say hi"])
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "hello world\n"
    assert out.err == ""


def test_reads_prompt_from_argv(fake_claude, set_stdin, capsys):
    fake_claude(ECHO_BODY)
    set_stdin("")
    main(["my prompt here"])
    assert capsys.readouterr().out.strip() == "my prompt here"


def test_reads_prompt_from_stdin(fake_claude, set_stdin, capsys):
    fake_claude(ECHO_BODY)
    set_stdin("piped prompt")
    main([])
    assert capsys.readouterr().out.strip() == "piped prompt"


def test_combines_argv_and_stdin(fake_claude, set_stdin, capsys):
    fake_claude(ECHO_BODY)
    set_stdin("the diff body")
    main(["review this"])
    out = capsys.readouterr().out
    assert "review this" in out
    assert "--- STDIN ---" in out
    assert "the diff body" in out


def test_rejects_empty_prompt(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    rc = main([])
    err = capsys.readouterr().err
    assert rc == 64  # no_prompt
    assert "no_prompt" in err


def test_no_prompt_json_envelope(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    rc = main(["--json"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 64
    assert env["ok"] is False
    assert env["kind"] == "no_prompt"


def test_json_envelope(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    rc = main(["--json", "hi"])
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["result"] == "hello world"
    assert env["session_id"] == UUID
    assert env["cost_usd"] == 0.0123
    assert isinstance(env["duration_ms"], int)
    assert env["raw"]["subtype"] == "success"


def test_raw_mode_emits_unchanged_json(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    main(["--raw", "hi"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["result"] == "hello world"
    assert data["session_id"] == UUID


def test_nonzero_exit_default_mode(fake_claude, set_stdin, capsys):
    fake_claude('sys.stderr.write("boom\\n"); sys.exit(3)')
    set_stdin("")
    rc = main(["hi"])
    err = capsys.readouterr().err
    assert rc == 3  # Claude's exit code is preserved
    assert "claude_exit_nonzero" in err


def test_nonzero_exit_json_mode(fake_claude, set_stdin, capsys):
    fake_claude('sys.stderr.write("boom\\n"); sys.exit(3)')
    set_stdin("")
    rc = main(["--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert env["ok"] is False
    assert env["kind"] == "claude_exit_nonzero"
    assert env["exit_code"] == 3
    assert "boom" in env["stderr"]


def test_invalid_json(fake_claude, set_stdin, capsys):
    fake_claude('print("not json {")')
    set_stdin("")
    rc = main(["--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 65
    assert env["kind"] == "invalid_json"


def test_auth_required_detected(fake_claude, set_stdin, capsys):
    fake_claude('sys.stderr.write("Invalid API key. Please run `claude /login`\\n"); sys.exit(1)')
    set_stdin("")
    rc = main(["--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert env["kind"] == "claude_auth_required"


def test_timeout(fake_claude, set_stdin, capsys):
    fake_claude("time.sleep(3); print('late')")
    set_stdin("")
    rc = main(["--timeout", "0.3", "hi"])
    err = capsys.readouterr().err
    assert rc == 124
    assert "claude_timeout" in err


def test_claude_not_found(monkeypatch, set_stdin, capsys):
    monkeypatch.setenv("CLAUDECMD_CLAUDE_BIN", "/no/such/claude-binary-xyz")
    set_stdin("")
    rc = main(["hi"])
    assert rc == 127
    assert "claude_not_found" in capsys.readouterr().err


def test_cwd_not_found(set_stdin, capsys):
    set_stdin("")
    rc = main(["--cwd", "/no/such/directory/here", "hi"])
    assert rc == 66
    assert "cwd_not_found" in capsys.readouterr().err


def test_passes_through_cwd(fake_claude, set_stdin, capsys, tmp_path):
    import os

    fake_claude('print(json.dumps({"result": os.getcwd(), "session_id": "x"}))')
    work = tmp_path / "work"
    work.mkdir()
    set_stdin("")
    main(["--json", "--cwd", str(work), "where am i"])
    env = json.loads(capsys.readouterr().out)
    assert env["result"] == os.path.realpath(str(work))


def test_dry_run_does_not_execute(fake_claude, set_stdin, capsys, tmp_path, monkeypatch):
    sentinel = tmp_path / "sentinel"
    monkeypatch.setenv("SENTINEL", str(sentinel))
    fake_claude('open(os.environ["SENTINEL"], "w").close()\nprint("{}")')
    set_stdin("")
    rc = main(["--dry-run", "hi there"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out
    assert "-p" in out
    assert "hi there" in out
    assert not sentinel.exists()  # Claude was never launched


def test_dry_run_json(fake_claude, set_stdin, capsys):
    fake_claude("print('{}')")
    set_stdin("")
    main(["--dry-run", "--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["dry_run"] is True
    assert "-p" in env["command"]
    assert "hi" in env["command"]


def test_updates_named_session_mapping(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    rc = main(["--session", "auth-refactor", "hello"])
    assert rc == 0
    assert SessionStore().resolve("auth-refactor") == UUID


def test_stream_mode_prints_assistant_text(fake_claude, set_stdin, capsys):
    fake_claude(STREAM_BODY)
    set_stdin("")
    rc = main(["--stream", "hi"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Hello world" in out


def test_stream_mode_updates_session(fake_claude, set_stdin, capsys):
    fake_claude(STREAM_BODY)
    set_stdin("")
    main(["--stream", "--session", "streamy", "hi"])
    assert SessionStore().resolve("streamy") == "sess-stream-1"


def test_raw_stream_echoes_event_lines(fake_claude, set_stdin, capsys):
    fake_claude(STREAM_BODY)
    set_stdin("")
    rc = main(["--raw", "--stream", "hi"])
    out = capsys.readouterr().out
    assert rc == 0
    # raw stream emits the verbatim event JSON lines
    lines = [l for l in out.splitlines() if l.strip()]
    assert any(json.loads(l).get("type") == "result" for l in lines)


def test_pty_flag_returns_plain_text(monkeypatch, set_stdin, capsys):
    monkeypatch.setattr("claudecmd.pty_runner.run_pty", lambda *a, **k: "pty plain output")
    set_stdin("")
    rc = main(["--pty", "hi"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "pty plain output"


def test_pty_json_envelope_has_null_metadata(monkeypatch, set_stdin, capsys):
    monkeypatch.setattr("claudecmd.pty_runner.run_pty", lambda *a, **k: "pty text")
    set_stdin("")
    main(["--pty", "--json", "hi"])
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["result"] == "pty text"
    assert env["session_id"] is None
    assert env["cost_usd"] is None


def test_auto_pty_fallback_on_tty_error(fake_claude, monkeypatch, set_stdin, capsys):
    # A normal run that fails with a TTY-related stderr should retry on PTY.
    fake_claude('sys.stderr.write("Raw mode is not supported on this stdin\\n"); sys.exit(1)')
    monkeypatch.setattr("claudecmd.pty_runner.run_pty", lambda *a, **k: "fallback output")
    set_stdin("")
    rc = main(["hi"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "fallback output"


def test_oversize_stdin_writes_and_cleans_temp_file(fake_claude, set_stdin, capsys):
    fake_claude(ECHO_BODY)
    set_stdin("z" * 5000)
    rc = main(["--max-stdin-bytes", "100", "--json", "do the thing"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 0
    # The prompt Claude received references a temp file, not the inlined blob.
    match = re.search(r"this file: (\S+)", env["result"])
    assert match, env["result"]
    temp_path = match.group(1)
    assert "z" * 5000 not in env["result"]
    # Deleted after the run (no --debug).
    assert not os.path.exists(temp_path)


def test_oversize_stdin_debug_keeps_temp_file(fake_claude, set_stdin, capsys):
    fake_claude(ECHO_BODY)
    set_stdin("y" * 5000)
    main(["--max-stdin-bytes", "100", "--debug", "keep it", "--json"])
    env = json.loads(capsys.readouterr().out)
    match = re.search(r"this file: (\S+)", env["result"])
    assert match
    temp_path = match.group(1)
    try:
        assert os.path.exists(temp_path)  # kept for inspection under --debug
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_dry_run_redacts_secrets(fake_claude, set_stdin, capsys):
    fake_claude(SUCCESS_BODY)
    set_stdin("")
    main(["--dry-run", "use API_KEY=topsecretvalue now"])
    out = capsys.readouterr().out
    assert "topsecretvalue" not in out
    assert "***REDACTED***" in out


def test_session_store_error_surfaces(fake_claude, set_stdin, capsys, monkeypatch):
    fake_claude(SUCCESS_BODY)
    set_stdin("")

    def boom(self, name_or_id):
        raise ClacmdError(SESSION_STORE_ERROR, "disk on fire")

    monkeypatch.setattr(SessionStore, "resolve", boom)
    rc = main(["--session", "whatever", "hi"])
    assert rc == 74
    assert "session_store_error" in capsys.readouterr().err
