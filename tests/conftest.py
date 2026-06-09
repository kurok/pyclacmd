"""Shared pytest fixtures.

The key idea: tests never need a real ``claude`` login.  ``fake_claude``
writes a tiny Python script, marks it executable, and points
``CLAUDECMD_CLAUDE_BIN`` at it, so the real subprocess machinery is exercised
end-to-end against deterministic, canned output.
"""

from __future__ import annotations

import io
import stat

import pytest

# A fake that echoes the prompt that was passed after ``-p`` back as the
# result — used to assert prompt-source behavior end to end.
ECHO_BODY = r"""
argv = sys.argv[1:]
prompt = ""
if "-p" in argv:
    i = argv.index("-p")
    if i + 1 < len(argv):
        prompt = argv[i + 1]
print(json.dumps({
    "type": "result",
    "subtype": "success",
    "result": prompt,
    "session_id": "11111111-1111-1111-1111-111111111111",
    "total_cost_usd": 0.0,
    "duration_ms": 1,
}))
"""

# A fake that returns a fixed successful JSON result.
SUCCESS_BODY = r"""
print(json.dumps({
    "type": "result",
    "subtype": "success",
    "result": "hello world",
    "session_id": "11111111-1111-1111-1111-111111111111",
    "total_cost_usd": 0.0123,
    "duration_ms": 42,
}))
"""


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Keep the session store inside the test's tmp dir, and point the
    Claude binary at a guaranteed-nonexistent path by default.

    This guarantees that any test which reaches execution without explicitly
    selecting a fake binary fails fast with ``claude_not_found`` rather than
    silently spawning a real, authenticated ``claude`` on the runner's PATH.
    """
    monkeypatch.setenv("CLAUDECMD_HOME", str(tmp_path / "cchome"))
    monkeypatch.setenv("CLAUDECMD_CLAUDE_BIN", str(tmp_path / "NO_REAL_CLAUDE"))
    yield


@pytest.fixture
def set_stdin(monkeypatch):
    """Replace sys.stdin with an in-memory pipe-like stream."""

    def _set(text: str = "") -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(text))

    return _set


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Create an executable fake ``claude`` and select it via env."""
    state = {"count": 0}

    def _make(body: str) -> str:
        state["count"] += 1
        path = tmp_path / "fake_claude_{}.py".format(state["count"])
        path.write_text("#!/usr/bin/env python3\nimport sys, json, os, time\n" + body + "\n")
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("CLAUDECMD_CLAUDE_BIN", str(path))
        return str(path)

    return _make
