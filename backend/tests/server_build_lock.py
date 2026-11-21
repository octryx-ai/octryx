"""Lifting the server build lock in a test that exercises the server pipeline itself.

The server never runs repository build/test tooling (``execution_runtime.foreign_build_guard``) and
never starts a run that declares a build or test step (``workflow_runs.runtime_target.server_build``); there is no
platform switch. The suites that cover the server pipeline's own mechanics (working copy, declared test/lint
commands, TDD evidence, slices, exec policy, script resolution, runs without a runtime target that a terminal
attaches to later) keep covering them, because the sandbox runtime runs exactly that pipeline: they lift the lock
with this monkeypatch, never the product. The lock itself is proven in ``test_foreign_build_guard`` and
``test_workflow_run_server_build_lock``.
"""

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
    """Tool mechanics tests without a database session: the fail-closed audit (``command_audit``) writes nothing."""
    from app.services.execution_runtime import command_audit

    async def no_row(*args, **kwargs):
        return None

    monkeypatch.setattr(command_audit, "record", no_row)


@pytest.fixture
def server_build_lock_lifted(monkeypatch: pytest.MonkeyPatch) -> None:
    lift_server_build_lock(monkeypatch)
