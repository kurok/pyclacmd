"""Local name -> session-id mapping with file locking.

Stored at ``~/.claudecmd/sessions.json`` (override the directory via the
``CLAUDECMD_HOME`` env var).  A UUID passed as a session is used directly and
never recorded; a friendly name is resolved through, and written back to,
this store after each successful run.

Concurrency safety: writes are guarded by an exclusive ``flock`` on a
sibling lock file, and the JSON is replaced atomically via ``os.replace``.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from .errors import ClacmdError, SESSION_STORE_ERROR

try:  # POSIX/macOS file locking; absent on some platforms (e.g. Windows).
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None  # type: ignore[assignment]
    _HAVE_FCNTL = False

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_uuid(value: Optional[str]) -> bool:
    return bool(value) and bool(_UUID_RE.match(value))  # type: ignore[arg-type]


def default_home() -> str:
    env = os.environ.get("CLAUDECMD_HOME")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".claudecmd")


def _utcnow() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


class SessionStore:
    def __init__(self, home: Optional[str] = None) -> None:
        self.home = home or default_home()
        self.path = os.path.join(self.home, "sessions.json")
        self.lock_path = os.path.join(self.home, "sessions.lock")

    # -- public API ---------------------------------------------------------
    def resolve(self, name_or_id: Optional[str]) -> Optional[str]:
        """Resolve a session arg to a concrete session id, if known.

        A UUID resolves to itself; a name resolves to its stored id, or
        ``None`` when the name has not been seen yet.
        """
        if name_or_id is None:
            return None
        if is_uuid(name_or_id):
            return name_or_id
        data = self._read()
        entry = data.get(name_or_id)
        if isinstance(entry, dict):
            sid = entry.get("session_id")
            return sid if isinstance(sid, str) else None
        return None

    def update(
        self,
        name: Optional[str],
        session_id: Optional[str],
        *,
        cwd: Optional[str] = None,
        now: Optional[str] = None,
    ) -> None:
        """Record ``name -> session_id``.  No-op for empty/UUID names."""
        if not name or not session_id or is_uuid(name):
            return
        timestamp = now or _utcnow()
        with self._locked():
            data = self._read_unlocked()
            entry = data.get(name)
            if not isinstance(entry, dict):
                entry = {}
            entry.setdefault("created_at", timestamp)
            entry["session_id"] = session_id
            entry["updated_at"] = timestamp
            if cwd:
                entry["cwd"] = cwd
            data[name] = entry
            self._write_unlocked(data)

    # -- internals ----------------------------------------------------------
    def _ensure_dir(self) -> None:
        try:
            os.makedirs(self.home, exist_ok=True)
            os.chmod(self.home, 0o700)
        except OSError as exc:
            raise ClacmdError(
                SESSION_STORE_ERROR,
                "Cannot create session directory {}: {}".format(self.home, exc),
            )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_dir()
        try:
            handle = open(self.lock_path, "a+")
        except OSError as exc:
            raise ClacmdError(
                SESSION_STORE_ERROR,
                "Cannot open session lock {}: {}".format(self.lock_path, exc),
            )
        try:
            if _HAVE_FCNTL:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if _HAVE_FCNTL:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _read(self) -> Dict[str, Any]:
        with self._locked():
            return self._read_unlocked()

    def _read_unlocked(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            # Corrupt store: preserve it for inspection, start fresh.
            try:
                os.replace(self.path, self.path + ".corrupt")
            except OSError:
                pass
            return {}
        except OSError as exc:
            raise ClacmdError(
                SESSION_STORE_ERROR,
                "Cannot read session store {}: {}".format(self.path, exc),
            )
        return data if isinstance(data, dict) else {}

    def _write_unlocked(self, data: Dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.home, prefix="sessions-", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise ClacmdError(
                SESSION_STORE_ERROR,
                "Cannot write session store {}: {}".format(self.path, exc),
            )
