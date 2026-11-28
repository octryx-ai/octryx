"""The launcher's heartbeat while Claude Code runs."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator

import httpx

from .platform import SessionContext, call_control_plane
from .state import LocalState

INTERVAL_SECONDS = 30.0
TIMEOUT_SECONDS = 5.0


def beat(state: LocalState, context: SessionContext, http: httpx.Client) -> bool:
    try:
        result = call_control_plane(state, context, "POST", "/sessions/heartbeat", http=http, timeout=TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - the session never depends on its heartbeat
        return False
    return result.outcome == "ok"


@contextlib.contextmanager
def running(state: LocalState, context: SessionContext, *, interval: float = INTERVAL_SECONDS,
            send: Callable[[LocalState, SessionContext, httpx.Client], bool] = beat) -> Iterator[threading.Event]:
    stop = threading.Event()

    def loop() -> None:
        with httpx.Client() as http:
            while not stop.wait(interval):
                send(state, context, http)

    thread = threading.Thread(target=loop, name="octryx-heartbeat", daemon=True)
    thread.start()
    try:
        yield stop
    finally:
        stop.set()


__all__ = ["INTERVAL_SECONDS", "beat", "running"]
