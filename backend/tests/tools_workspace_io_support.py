"""Shared helpers for the test_tools_workspace_io_* modules."""

import subprocess
from pathlib import Path

import pytest


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_command_audit, lift_server_build_lock

    lift_server_build_lock(monkeypatch)
    lift_command_audit(monkeypatch)
