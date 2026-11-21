"""A phase whose test runner could not start pauses the run ``environment_not_ready`` (no loop iteration consumed).

The newest test command of a phase turn that could not start its runner (``workflow_checks.test_command_outcome``:
exit 127/126, command not found, the runner's module missing, the runner failing while it loads) is the
environment's failure, not the agent's: the run pauses at the phase with the exact reason; the phase's result is not
reported, so no gate runs and no loop counter moves. **Retry** (``continue``) re-enters the phase as a new pass after
the person fixed the environment (``pause._resume`` kind ``restart``); change plan and abort are offered as usual.

The pause is also the guard against automatic device continuations: a continuation starts only for a running run
(``octryx.continuation``), so a device turn that hit the environment can never be followed by another one by itself.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from ..states import PAUSE_ENVIRONMENT_NOT_READY

CONTEXT_KEY = "environment_failure"


def fingerprint(failure: dict[str, Any]) -> str:
    text = f"{failure.get('reason') or ''}|{failure.get('command') or ''}"
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()[:32]


async def pause_not_ready(db: AsyncSession, run: WorkflowRun, failure: dict[str, Any]) -> None:
    """Pause the run at its current phase for ``failure`` (``reason``, optionally ``command`` / ``excerpt``)."""
    from ..limits import pause_run

    reason = str(failure.get("reason") or "the test environment is not ready")
    command = str(failure.get("command") or "")
    recorded = {**{key: value for key, value in failure.items() if key in (
        "kind", "reason", "command", "exit_code", "excerpt", "source", "session_id")},
        "node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"),
        "fingerprint": fingerprint(failure), "at": utc_now().isoformat()}
    run.context = {**dict(run.context or {}), CONTEXT_KEY: recorded}
    # A preparation report names the folder (branch, repository, environment), a test command the runner.
    head = {"workspace_preparation": "The working folder is not ready",
            "declared_lint": "The declared lint command could not run",
            "pipeline": "The pipeline could not run a declared command"}.get(str(failure.get("source") or ""),
                                                                            "The tests could not run")
    message = f"{head}: {reason}" + (f" (command: {command[:200]})" if command else "") + (
        ". Fix the environment in the working folder (or declare the repository's environment setup), then retry.")
    await pause_run(db, run, reason=PAUSE_ENVIRONMENT_NOT_READY, actor_id=None, detail={
        "message": message, "failure": recorded,
        "resume": {"kind": "restart", "node_id": run.current_node_id},
    })


__all__ = ["CONTEXT_KEY", "fingerprint", "pause_not_ready"]
