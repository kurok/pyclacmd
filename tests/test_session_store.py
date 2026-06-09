from __future__ import annotations

import json
import os

import pytest

from claudecmd import session_store
from claudecmd.errors import ClacmdError, SESSION_STORE_ERROR
from claudecmd.session_store import SessionStore, is_uuid

UUID = "00000000-0000-0000-0000-000000000000"


def test_is_uuid():
    assert is_uuid(UUID)
    assert not is_uuid("auth-refactor")
    assert not is_uuid(None)


def test_resolve_uuid_passthrough(tmp_path):
    store = SessionStore(home=str(tmp_path / "h"))
    assert store.resolve(UUID) == UUID


def test_resolve_unknown_name_is_none(tmp_path):
    store = SessionStore(home=str(tmp_path / "h"))
    assert store.resolve("never-seen") is None


def test_update_then_resolve(tmp_path):
    home = str(tmp_path / "h")
    store = SessionStore(home=home)
    store.update("auth-refactor", UUID, cwd="/repo", now="2026-06-09T12:00:00Z")
    assert store.resolve("auth-refactor") == UUID

    with open(os.path.join(home, "sessions.json")) as handle:
        data = json.load(handle)
    entry = data["auth-refactor"]
    assert entry["session_id"] == UUID
    assert entry["cwd"] == "/repo"
    assert entry["created_at"] == "2026-06-09T12:00:00Z"
    assert entry["updated_at"] == "2026-06-09T12:00:00Z"


def test_update_preserves_created_at(tmp_path):
    store = SessionStore(home=str(tmp_path / "h"))
    store.update("name", UUID, now="2026-01-01T00:00:00Z")
    store.update("name", UUID, now="2026-02-02T00:00:00Z")
    sid = store.resolve("name")
    assert sid == UUID
    with open(store.path) as handle:
        entry = json.load(handle)["name"]
    assert entry["created_at"] == "2026-01-01T00:00:00Z"
    assert entry["updated_at"] == "2026-02-02T00:00:00Z"


def test_update_ignores_uuid_name(tmp_path):
    store = SessionStore(home=str(tmp_path / "h"))
    store.update(UUID, UUID)  # raw uuid name is never recorded
    assert not os.path.exists(store.path)


def test_permissions_are_restrictive(tmp_path):
    store = SessionStore(home=str(tmp_path / "h"))
    store.update("name", UUID)
    assert (os.stat(store.home).st_mode & 0o777) == 0o700
    assert (os.stat(store.path).st_mode & 0o777) == 0o600


def test_corrupt_store_is_backed_up_and_reset(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (home / "sessions.json").write_text("{ this is not json")
    store = SessionStore(home=str(home))
    assert store.resolve("anything") is None
    assert os.path.exists(str(home / "sessions.json.corrupt"))


def test_store_failure_raises_session_store_error(tmp_path, monkeypatch):
    store = SessionStore(home=str(tmp_path / "h"))

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(session_store.os, "makedirs", boom)
    with pytest.raises(ClacmdError) as exc:
        store.update("name", UUID)
    assert exc.value.kind == SESSION_STORE_ERROR


def test_update_uses_file_locking(tmp_path, monkeypatch):
    calls = []
    real_flock = session_store.fcntl.flock

    def recording_flock(fd, op):
        calls.append(op)
        return real_flock(fd, op)

    monkeypatch.setattr(session_store.fcntl, "flock", recording_flock)
    store = SessionStore(home=str(tmp_path / "h"))
    store.update("name", UUID)

    assert session_store.fcntl.LOCK_EX in calls
    assert session_store.fcntl.LOCK_UN in calls
    assert os.path.exists(store.lock_path)
