"""Cooperative cancellation. Signal handlers set the token; the engine and runner poll it."""

from __future__ import annotations

import signal
import threading
from types import FrameType


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason = ""

    def cancel(self, reason: str = "cancelled") -> None:
        self.reason = reason
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


def install_signal_handlers(token: CancellationToken) -> dict[int, object]:
    """Route SIGINT and SIGTERM to the token. Returns the previous handlers for restoring."""
    previous: dict[int, object] = {}

    def handler(signum: int, _frame: FrameType | None) -> None:
        token.cancel(signal.Signals(signum).name)

    if threading.current_thread() is not threading.main_thread():
        return previous
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, handler)
    return previous


def restore_signal_handlers(previous: dict[int, object]) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)  # type: ignore[arg-type]
