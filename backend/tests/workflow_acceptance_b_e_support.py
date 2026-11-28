"""Shared helpers for the test_workflow_acceptance_b_e_* modules."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
