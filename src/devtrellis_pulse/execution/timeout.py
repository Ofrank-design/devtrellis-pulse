from __future__ import annotations

from typing import Any

from devtrellis_pulse.execution.limits import Budget


def effective_timeout(requested: float | None, cfg: dict[str, Any], budget: Budget) -> float:
    """The smallest of the request, the per task cap and the time left in the run."""
    cap = float(cfg["runtime"]["max_task_runtime_seconds"])
    limit = min(requested, cap) if requested else cap
    return max(min(limit, budget.remaining_seconds()), 0.1)
