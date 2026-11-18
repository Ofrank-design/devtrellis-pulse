"""Structured diagnostic logging to stderr. Messages are redacted before they are written."""

from __future__ import annotations

import logging
import sys

from devtrellis_pulse.validation.secret_scan import redact

LOGGER_NAME = "devtrellis_pulse"


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        stamp = self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ")
        parts = [stamp, record.levelname.lower()]
        for key in ("run_id", "task_id", "event", "duration_ms", "error_code"):
            value = getattr(record, key, None)
            if value not in (None, ""):
                parts.append(f"{key}={value}")
        parts.append(record.getMessage())
        return redact(" ".join(parts))


def configure(verbose: bool = False, quiet: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_RedactingFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    if quiet:
        logger.setLevel(logging.ERROR)
    elif verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.WARNING)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
