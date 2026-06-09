"""Best-effort secret redaction for debug logs and dry-run command plans.

This is a defensive convenience, not a security guarantee.  It masks the
most common shapes of credentials so that ``--debug`` output and the
``--dry-run`` command plan do not casually leak secrets that happen to be
embedded in a prompt or environment-style text.
"""

from __future__ import annotations

import re
from typing import Iterable, List

REDACTED = "***REDACTED***"

# Order matters: structured "key = value" patterns run before bare-token
# patterns so the value (not just a substring) gets masked.
_PATTERNS = [
    # Authorization: Bearer <token>  /  Authorization: <token>
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?\S+"),
        lambda m: m.group(1) + (m.group(2) or "") + REDACTED,
    ),
    # KEY=VALUE / KEY: VALUE for sensitive-looking key names (.env style)
    (
        re.compile(
            r"(?im)([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|"
            r"ACCESS[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL)[A-Z0-9_]*\s*[:=]\s*)"
            r"(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        lambda m: m.group(1) + REDACTED,
    ),
    # password = <value> (any case, common inline form)
    (
        re.compile(r"(?i)(password\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"),
        lambda m: m.group(1) + REDACTED,
    ),
    # Anthropic-style keys
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), lambda m: REDACTED),
    # OpenAI / generic sk- keys
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), lambda m: REDACTED),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), lambda m: REDACTED),
    # AWS access key id
    (re.compile(r"AKIA[0-9A-Z]{16}"), lambda m: REDACTED),
    # Slack tokens
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), lambda m: REDACTED),
]


def redact(text: str) -> str:
    """Return ``text`` with obvious secrets replaced by ``***REDACTED***``."""
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_argv(argv: Iterable[str]) -> List[str]:
    """Redact each element of a command argument vector."""
    return [redact(str(arg)) for arg in argv]
