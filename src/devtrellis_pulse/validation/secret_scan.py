"""Secret detection and redaction. Matches are never echoed back, only their kind and line."""

from __future__ import annotations

import re

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "credential_assignment": re.compile(
        r"""(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['"][^'"\s]{8,}['"]"""
    ),
    "url_credentials": re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@"),
}


def scan_text(text: str) -> list[tuple[str, int]]:
    """Return (kind, line number) for each suspected secret."""
    hits: list[tuple[str, int]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                hits.append((kind, number))
    return hits


def redact(text: str, extra_patterns: list[str] | None = None) -> str:
    for pattern in SECRET_PATTERNS.values():
        text = pattern.sub("[REDACTED]", text)
    for raw in extra_patterns or []:
        text = re.sub(raw, "[REDACTED]", text)
    return text


def redact_obj(value, extra_patterns: list[str] | None = None):
    """Redact every string inside a JSON like structure (safe to serialize afterwards)."""
    if isinstance(value, str):
        return redact(value, extra_patterns)
    if isinstance(value, dict):
        return {k: redact_obj(v, extra_patterns) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v, extra_patterns) for v in value]
    return value
