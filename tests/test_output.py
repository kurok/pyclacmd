from __future__ import annotations

import io
import json

import pytest

from claudecmd.errors import ClacmdError, INVALID_JSON
from claudecmd import output


def test_parse_and_extract():
    raw = json.dumps(
        {
            "result": "the answer",
            "session_id": "sid-1",
            "total_cost_usd": 0.25,
            "duration_ms": 99,
        }
    )
    data = output.parse_claude_json(raw)
    assert output.extract_result_text(data) == "the answer"
    assert output.extract_session_id(data) == "sid-1"
    assert output.extract_cost(data) == 0.25
    assert output.extract_duration(data) == 99


def test_parse_invalid_json_raises():
    with pytest.raises(ClacmdError) as exc:
        output.parse_claude_json("not json {")
    assert exc.value.kind == INVALID_JSON


def test_parse_empty_raises():
    with pytest.raises(ClacmdError) as exc:
        output.parse_claude_json("   ")
    assert exc.value.kind == INVALID_JSON


def test_cost_ignores_bool():
    # ``True`` is an int subclass; it must not be read as a cost.
    assert output.extract_cost({"total_cost_usd": True}) is None


def test_success_envelope_shape():
    env = output.success_envelope("r", "sid", 10, 0.5, {"x": 1})
    assert env == {
        "ok": True,
        "result": "r",
        "session_id": "sid",
        "duration_ms": 10,
        "cost_usd": 0.5,
        "raw": {"x": 1},
    }


def _events(*objs):
    return [json.dumps(o) for o in objs]


def test_stream_processor_emits_assistant_text():
    out = io.StringIO()
    proc = output.StreamProcessor(raw=False, out=out)
    for line in _events(
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello "}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "world"}]}},
        {"type": "result", "subtype": "success", "result": "Hello world",
         "session_id": "s1", "total_cost_usd": 0.01},
    ):
        proc.handle_line(line)
    assert out.getvalue().startswith("Hello world")
    assert proc.session_id == "s1"
    assert proc.cost_usd == 0.01
    assert proc.result_text() == "Hello world"


def test_stream_processor_raw_echoes_lines():
    out = io.StringIO()
    proc = output.StreamProcessor(raw=True, out=out)
    lines = _events(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "result", "result": "hi", "session_id": "s2"},
    )
    for line in lines:
        proc.handle_line(line)
    emitted = out.getvalue().splitlines()
    assert emitted == lines
    assert proc.session_id == "s2"


def test_stream_processor_ignores_garbage_lines():
    out = io.StringIO()
    proc = output.StreamProcessor(raw=False, out=out)
    proc.handle_line("not json")
    proc.handle_line("")
    assert out.getvalue() == ""
