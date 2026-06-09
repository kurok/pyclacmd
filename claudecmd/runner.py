"""Subprocess execution of the ``claude`` CLI with timeout handling.

Two entry points:
  * :func:`run`        - buffered execution, returns the full RunResult.
  * :func:`run_stream` - line-streaming execution, invoking ``on_line`` per
                         stdout line as it arrives.

Both translate process-spawn failures into :class:`ClacmdError` with the
appropriate ``kind`` and never use a shell.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from .errors import ClacmdError, CLAUDE_NOT_FOUND, CLAUDE_TIMEOUT

# Grace period between SIGTERM and SIGKILL when forcing a timeout.
_KILL_GRACE_SECONDS = 5.0


@dataclass
class RunResult:
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int


def _spawn(argv: List[str], cwd: Optional[str], *, stream: bool) -> "subprocess.Popen":
    kwargs = dict(
        cwd=cwd,
        # The prompt always travels via argv, so Claude must never read our
        # stdin; closing it prevents the child from blocking on a TTY.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if stream:
        kwargs["bufsize"] = 1  # line-buffered
    if os.name == "posix":
        # Put the child in its own process group so a timeout can tear down
        # the whole tree (claude plus any helper subprocesses it spawns);
        # otherwise grandchildren keep the stdout pipe open and we hang.
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]
    except FileNotFoundError:
        raise ClacmdError(
            CLAUDE_NOT_FOUND, "Claude Code CLI not found: {}".format(argv[0])
        )
    except PermissionError:
        raise ClacmdError(
            CLAUDE_NOT_FOUND, "Claude Code CLI is not executable: {}".format(argv[0])
        )


def run(
    argv: List[str],
    *,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> RunResult:
    """Run ``argv`` to completion, capturing stdout/stderr."""
    start = time.monotonic()
    proc = _spawn(argv, cwd, stream=False)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        try:
            proc.communicate(timeout=_KILL_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
        duration = int((time.monotonic() - start) * 1000)
        raise ClacmdError(
            CLAUDE_TIMEOUT,
            "Claude command timed out after {}s".format(timeout),
            extra={"duration_ms": duration},
        )
    except BaseException:
        # Ctrl-C or any unexpected failure: never leave the child running.
        _terminate(proc)
        raise
    duration = int((time.monotonic() - start) * 1000)
    return RunResult(stdout or "", stderr or "", proc.returncode, duration)


def run_stream(
    argv: List[str],
    *,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
    on_line: Optional[Callable[[str], None]] = None,
) -> RunResult:
    """Run ``argv`` and invoke ``on_line`` for each stdout line as it arrives.

    stderr is buffered and returned.  stdout is consumed by the callback, so
    ``RunResult.stdout`` is empty for streaming runs.
    """
    start = time.monotonic()
    proc = _spawn(argv, cwd, stream=True)

    # Drain stderr concurrently so a chatty child can't fill the stderr pipe
    # buffer and deadlock against us while we read stdout.
    stderr_chunks: List[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                stderr_chunks.append(line)
        except (OSError, ValueError):
            pass

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    timed_out = {"value": False}
    timer: Optional[threading.Timer] = None
    if timeout is not None:
        def _on_timeout() -> None:
            timed_out["value"] = True
            _terminate(proc)

        timer = threading.Timer(timeout, _on_timeout)
        timer.daemon = True
        timer.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_line is not None:
                on_line(line.rstrip("\n"))
        proc.wait()
    finally:
        # Always tear the child down — if on_line raised (e.g. a broken
        # downstream pipe), the process must not be left orphaned.
        if timer is not None:
            timer.cancel()
        if proc.poll() is None:
            _terminate(proc)
        stderr_thread.join(timeout=_KILL_GRACE_SECONDS)

    stderr = "".join(stderr_chunks)
    duration = int((time.monotonic() - start) * 1000)

    if timed_out["value"]:
        raise ClacmdError(
            CLAUDE_TIMEOUT,
            "Claude command timed out after {}s".format(timeout),
            stderr=stderr.strip() or None,
            extra={"duration_ms": duration},
        )
    return RunResult("", stderr, proc.returncode, duration)


def _terminate(proc: "subprocess.Popen") -> None:
    """Terminate cleanly, escalating to SIGKILL if the process won't exit.

    Targets the child's process group when possible so helper subprocesses
    Claude spawned are torn down too (otherwise a survivor can hold the
    stdout pipe open and hang the reader).
    """
    if proc.poll() is not None:
        return
    if not _signal_group(proc, signal.SIGTERM):
        try:
            proc.terminate()
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    if not _signal_group(proc, signal.SIGKILL):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _signal_group(proc: "subprocess.Popen", sig: int) -> bool:
    """Signal the child's whole process group; return True if it was sent.

    Only fires when the child is its own group leader (i.e. it was spawned
    with ``start_new_session``), so we can never accidentally signal our own
    process group.
    """
    if os.name != "posix":
        return False
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        return False
    if pgid != proc.pid:
        return False
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, OSError):
        return False
