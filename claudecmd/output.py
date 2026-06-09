"""The stable claudecmd ``--json`` output envelope."""

from __future__ import annotations

from typing import Any, Dict, Optional


def success_envelope(
    result: str,
    session_id: Optional[str],
    duration_ms: Optional[int],
    cost_usd: Optional[float],
    raw: Any,
) -> Dict[str, Any]:
    """The stable ``--json`` success envelope.

    For the interactive path ``session_id``, ``cost_usd``, and ``raw`` are not
    available from the TUI and are emitted as ``null``.
    """
    return {
        "ok": True,
        "result": result,
        "session_id": session_id,
        "duration_ms": duration_ms,
        "cost_usd": cost_usd,
        "raw": raw,
    }
