"""Small deterministic redaction helpers for persisted diagnostic text."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_URL_CREDENTIALS = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@", re.IGNORECASE)


def sanitize_diagnostic_text(value: str, *, max_length: int = 2_000) -> str:
    """Redact common credential shapes and bound persisted diagnostic text."""
    redacted = _BEARER.sub("Bearer [REDACTED]", value)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)
    redacted = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", redacted)
    if len(redacted) > max_length:
        return redacted[: max_length - 1] + "…"
    return redacted
