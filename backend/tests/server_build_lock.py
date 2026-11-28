"""Lifts the server build lock for suites that cover the server pipeline's own mechanics, which the sandbox runtime
runs; the lock itself is proven in ``test_foreign_build_guard``."""

from __future__ import annotations

import pytest

from app.services.execution_runtime import build_guard_rules, foreign_build_guard
from app.services.workflow_runs.runtime_target import server_build

_ALLOWED = foreign_build_guard.ForeignBuildVerdict(blocked=False, command_class=build_guard_rules.CLASS_ALLOWED)


def lift_server_build_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(foreign_build_guard, "classify_command", lambda command, **_: _ALLOWED)
    monkeypatch.setattr(foreign_build_guard, "repository_path_verdict", lambda command, path_dirs: None)
    monkeypatch.setattr(server_build, "build_steps", lambda *args, **kwargs: [])


def lift_command_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.execution_runtime import command_audit

    async def no_row(*args, **kwargs):
        return None

    monkeypatch.setattr(command_audit, "record", no_row)


@pytest.fixture
def server_build_lock_lifted(monkeypatch: pytest.MonkeyPatch) -> None:
    lift_server_build_lock(monkeypatch)
