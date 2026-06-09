from __future__ import annotations

import os

import pytest

from claudecmd import runner
from claudecmd.errors import ClacmdError, CLAUDE_NOT_FOUND, CLAUDE_TIMEOUT


def test_run_captures_stdout(fake_claude):
    bin_ = fake_claude('print("ok output")')
    result = runner.run([bin_])
    assert result.stdout.strip() == "ok output"
    assert result.returncode == 0
    assert result.duration_ms >= 0


def test_run_captures_nonzero_and_stderr(fake_claude):
    bin_ = fake_claude('sys.stderr.write("boom\\n"); sys.exit(3)')
    result = runner.run([bin_])
    assert result.returncode == 3
    assert "boom" in result.stderr


def test_run_passes_cwd(fake_claude, tmp_path):
    bin_ = fake_claude("print(os.getcwd())")
    sub = tmp_path / "subdir"
    sub.mkdir()
    result = runner.run([bin_], cwd=str(sub))
    assert result.stdout.strip() == os.path.realpath(str(sub))


def test_run_claude_not_found():
    with pytest.raises(ClacmdError) as exc:
        runner.run(["/no/such/claude-binary-xyz"])
    assert exc.value.kind == CLAUDE_NOT_FOUND


def test_run_timeout(fake_claude):
    bin_ = fake_claude("time.sleep(3); print('late')")
    with pytest.raises(ClacmdError) as exc:
        runner.run([bin_], timeout=0.3)
    assert exc.value.kind == CLAUDE_TIMEOUT
    assert "duration_ms" in exc.value.extra


def test_run_stream_invokes_callback_per_line(fake_claude):
    bin_ = fake_claude(
        'print("line one", flush=True)\nprint("line two", flush=True)'
    )
    lines = []
    result = runner.run_stream([bin_], on_line=lines.append)
    assert lines == ["line one", "line two"]
    assert result.returncode == 0


def test_run_stream_timeout(fake_claude):
    bin_ = fake_claude("time.sleep(3); print('late', flush=True)")
    with pytest.raises(ClacmdError) as exc:
        runner.run_stream([bin_], timeout=0.3, on_line=lambda _l: None)
    assert exc.value.kind == CLAUDE_TIMEOUT


def test_run_stream_no_deadlock_on_large_stderr(fake_claude):
    # A child that fills the stderr pipe buffer (~64KB) before emitting stdout
    # must not deadlock against the stdout reader. Regression guard for the
    # concurrent stderr drain.
    bin_ = fake_claude(
        'sys.stderr.write("E" * 300000)\nsys.stderr.flush()\nprint("done", flush=True)'
    )
    lines = []
    result = runner.run_stream([bin_], timeout=20, on_line=lines.append)
    assert lines == ["done"]
    assert result.returncode == 0
    assert len(result.stderr) >= 300000


def test_run_stream_terminates_child_when_callback_raises(fake_claude, monkeypatch):
    # If on_line raises (e.g. a broken downstream pipe), the child must be
    # torn down in the finally block, not orphaned.
    bin_ = fake_claude('print("first", flush=True)\ntime.sleep(30)')
    terminated = []
    real_terminate = runner._terminate
    monkeypatch.setattr(
        runner, "_terminate", lambda p: (terminated.append(p), real_terminate(p))
    )

    def boom(_line):
        raise RuntimeError("downstream closed")

    with pytest.raises(RuntimeError):
        runner.run_stream([bin_], on_line=boom)
    assert terminated, "child process was not terminated on callback exception"
