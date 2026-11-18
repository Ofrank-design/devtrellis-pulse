"""Task output handling: output is data, never instructions. Redact and bound it before keeping."""

from __future__ import annotations

from devtrellis_pulse.validation.secret_scan import redact


def sanitize_output(text: str, patterns: list[str] | None = None, max_lines: int = 15) -> str:
    """Redact secrets and keep only the last `max_lines` lines."""
    lines = redact(text, patterns).splitlines()
    return "\n".join(lines[-max_lines:])
