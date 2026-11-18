from __future__ import annotations

import secrets

from devtrellis_pulse.core.clock import utc_now


def new_run_id() -> str:
    return "run_" + utc_now().strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)


def new_event_id() -> str:
    return "evt_" + secrets.token_hex(8)
