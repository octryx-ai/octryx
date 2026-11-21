"""Lifts the server build lock and command audit for the tool turn execution routing tests."""

import pytest


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_command_audit, lift_server_build_lock

    lift_server_build_lock(monkeypatch)
    lift_command_audit(monkeypatch)
