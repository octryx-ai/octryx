"""What a refused agent can do instead, said with the refusal: inform before, never let the agent start from zero.

Without it, one run was refused `cd e2e/node && npm test` three times and paused; another was refused the same protected
test five times, each with the same text. So the refusal names the concrete form this run allows: the run's declared
test command in its app folder, or for a confirmed test what to change instead. A refusal the run already got for the
same intent says so, so the agent changes its approach instead of retrying (``refusals.times_refused``). The texts are
catalog data (``run.block.instead_*``, ``run.block.again``).
"""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun


def _test_command(run: WorkflowRun) -> tuple[str, str]:
    """The run's declared test command and its app folder (pinned at preparation, else the record's declaration)."""
    from .workspace.contract_pin import commands, pin
    from .workspace.run_app import APP_KEY

    pinned = commands(run) or {}
    environment = dict((pin(run) or {}).get("environment") or {})
    command = str(pinned.get("test") or environment.get("test") or "").strip()
    folder = str(dict(dict(run.context or {}).get(APP_KEY) or {}).get("path") or ".").strip("/") or "."
    return command, folder


def instead(run: WorkflowRun | None, *, reason: str, tool: str, tool_input: dict[str, Any]) -> str:
    """The sentence the refusal gets for this run, ``""`` when there is nothing concrete to say."""
    from .refusals import times_refused
    from .run_texts import run_text

    if run is None:
        return ""
    path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    hint = ""
    if reason == "outside_phase_tools" and tool == "Bash":
        command, folder = _test_command(run)
        if command:
            hint = run_text("block.instead_test", command=command, folder=folder)
    elif reason == "confirmed_test_protected":
        hint = run_text("block.instead_confirmed", path=path)
    times = times_refused(run, tool, tool_input)
    if times >= 2:
        hint = f"{run_text('block.again', times=str(times))} {hint}".strip()
    return hint


__all__ = ["instead"]
