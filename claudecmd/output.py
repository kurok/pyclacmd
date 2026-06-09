"""Parsing Claude Code output and formatting the claudecmd output contract.

Covers three shapes:
  * JSON result object (``--output-format json``) -> extract result/session/cost
  * stable claudecmd success/error envelopes (``--json`` mode)
  * newline-delimited stream events (``--output-format stream-json``)
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, TextIO

from .errors import ClacmdError, INVALID_JSON

# Keys we look at, most-specific first, to stay resilient across Claude
# Code versions and minor shape changes.
_RESULT_KEYS = ("result", "response", "text", "content")
_COST_KEYS = ("total_cost_usd", "cost_usd", "costUSD", "total_cost")
_SESSION_KEYS = ("session_id", "sessionId")
_DURATION_KEYS = ("duration_ms", "durationMs")


def parse_claude_json(stdout: str) -> Dict[str, Any]:
    """Parse Claude's JSON result object, raising INVALID_JSON on failure."""
    text = (stdout or "").strip()
    if not text:
        raise ClacmdError(
            INVALID_JSON, "Claude returned empty output where JSON was expected."
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClacmdError(
            INVALID_JSON,
            "Failed to parse Claude JSON output: {}".format(exc),
        )
    if not isinstance(data, dict):
        # Some formats may emit a bare value; wrap it so callers see a dict.
        return {"result": data}
    return data


def extract_result_text(data: Dict[str, Any]) -> str:
    for key in _RESULT_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


def extract_session_id(data: Dict[str, Any]) -> Optional[str]:
    for key in _SESSION_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def extract_cost(data: Dict[str, Any]) -> Optional[float]:
    for key in _COST_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def extract_duration(data: Dict[str, Any]) -> Optional[int]:
    for key in _DURATION_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def success_envelope(
    result: str,
    session_id: Optional[str],
    duration_ms: Optional[int],
    cost_usd: Optional[float],
    raw: Any,
) -> Dict[str, Any]:
    """The stable ``--json`` success envelope."""
    return {
        "ok": True,
        "result": result,
        "session_id": session_id,
        "duration_ms": duration_ms,
        "cost_usd": cost_usd,
        "raw": raw,
    }


class StreamProcessor:
    """Consume newline-delimited stream-json events.

    In default mode it writes only assistant text blocks to ``out`` as they
    arrive.  In ``raw`` mode it echoes each event line verbatim.  Either way
    it captures session id / cost / the final result event for the caller.
    """

    def __init__(self, raw: bool = False, out: Optional[TextIO] = None) -> None:
        self.raw = raw
        self.out = out if out is not None else sys.stdout
        self.session_id: Optional[str] = None
        self.cost_usd: Optional[float] = None
        self.final: Optional[Dict[str, Any]] = None
        self._wrote_text = False

    def handle_line(self, line: str) -> None:
        if line is None or line.strip() == "":
            return

        if self.raw:
            self.out.write(line + "\n")
            self.out.flush()
            event = _try_load(line)
            if event is not None:
                self._capture(event)
            return

        event = _try_load(line)
        if event is None:
            return

        etype = event.get("type")
        if etype == "assistant":
            self._emit_assistant_text(event)
        elif etype == "result":
            self.final = event
            if self._wrote_text:
                self.out.write("\n")
                self.out.flush()
        self._capture(event)

    def _emit_assistant_text(self, event: Dict[str, Any]) -> None:
        message = event.get("message") or {}
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text") or ""
                if text:
                    self.out.write(text)
                    self.out.flush()
                    self._wrote_text = True

    def _capture(self, event: Dict[str, Any]) -> None:
        for key in _SESSION_KEYS:
            value = event.get(key)
            if isinstance(value, str) and value:
                self.session_id = value
        for key in _COST_KEYS:
            value = event.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.cost_usd = float(value)
        if event.get("type") == "result":
            self.final = event

    def result_text(self) -> str:
        if self.final:
            text = self.final.get("result")
            if isinstance(text, str):
                return text
        return ""


def _try_load(line: str) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
