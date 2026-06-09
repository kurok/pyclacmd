from __future__ import annotations

from claudecmd.output import success_envelope


def test_success_envelope_shape():
    env = success_envelope("the reply", "sess-1", 1234, 0.02, {"x": 1})
    assert env == {
        "ok": True,
        "result": "the reply",
        "session_id": "sess-1",
        "duration_ms": 1234,
        "cost_usd": 0.02,
        "raw": {"x": 1},
    }


def test_success_envelope_interactive_nulls():
    # The interactive path has no session id / cost / raw.
    env = success_envelope("hi", None, 500, None, None)
    assert env["ok"] is True
    assert env["result"] == "hi"
    assert env["session_id"] is None
    assert env["cost_usd"] is None
    assert env["raw"] is None
