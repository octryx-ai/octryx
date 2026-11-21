"""The autouse server pipeline fixture shared by the test_chat_approvals_* topic modules split from test_chat_approvals_b.py."""

import pytest


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
