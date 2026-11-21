"""Every end of the device service is in its log: it never ends without a line in device.log."""

from __future__ import annotations

import asyncio
import logging
import signal

import pytest

from octryx_claude.device_runtime import STOP_SIGNALS, on_stop_signal, run_logged

LOGGER = logging.getLogger("octryx_claude.device")


def test_a_stop_signal_is_logged_and_stops_the_service(caplog):
    stop = asyncio.Event()
    with caplog.at_level("WARNING", logger="octryx_claude.device"):
        on_stop_signal(LOGGER, stop, signal.SIGHUP)
    assert stop.is_set() and "SIGHUP received" in caplog.text
    assert signal.SIGHUP in STOP_SIGNALS


def test_a_crash_is_logged_with_its_traceback_and_a_regular_end_too(caplog):
    def crash():
        raise TimeoutError("handshake")

    with caplog.at_level("INFO", logger="octryx_claude.device"):
        with pytest.raises(TimeoutError):
            run_logged(LOGGER, crash)
        assert any(r.exc_info and "unhandled exception" in r.getMessage() for r in caplog.records)
        assert run_logged(LOGGER, lambda: "done") == "done" and "device service stopped" in caplog.text
