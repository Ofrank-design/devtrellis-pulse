"""Versioned JSON report."""

from __future__ import annotations

import json
from typing import Any

from devtrellis_pulse.reports.summary import build_summary
from devtrellis_pulse.validation.secret_scan import redact_obj

REPORT_SCHEMA_VERSION = 1


def to_json(run: dict[str, Any], patterns: list[str] | None = None) -> str:
    document = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "summary": build_summary(run),
        "run": run,
    }
    return json.dumps(redact_obj(document, patterns), indent=2, sort_keys=True, default=str) + "\n"
