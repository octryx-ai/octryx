"""The gateway hooks of a run-bound octryx-claude session: what each hook answer adds.

- PreToolUse (``agent_gateway/tool_decision``): the run's decision (``tool_policy``) replaces the session's
  workflow-tool and capability steps; the launcher's facts are recorded under the run claim first, and the run is
  claimed only when they change it;
- Stop / SubagentStop (``api/routes/agent_gateway``): ``stop.run_stop`` replaces the Workspace test gate;
- every answer of a bound session carries the refreshed contract (``workflow_run``).

A session that follows no run is untouched: every function returns ``None`` for it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ...agent_gateway.tool_check import ToolDecision
from ...workflow_checks.test_results import DEFAULT_TEST_PREFIXES
from ..records import active_run_for_session, lock_run
from .contract import run_contract, session_principal
from .facts import FACTS_KEY, facts_change, record_facts

logger = logging.getLogger(__name__)

def test_prefixes(policy: Any) -> tuple[tuple[str, ...], ...]:
    """The Workspace's test command prefixes (else the defaults) plus every stack's runner (``stacks.json``).

    Without the stack runners, `node --test` was no test run for the Stop, so "the test suite ran" and "the
    last test run passed" failed four times on a fixed, green phase; the runners are data, never a list in code."""
    from ...engineering_knowledge.stacks import test_runners

    verification = getattr(policy, "verification", None)
    prefixes = getattr(verification, "test_command_prefixes", None) if verification is not None else None
    own = tuple(tuple(item) for item in prefixes) if prefixes else DEFAULT_TEST_PREFIXES
    runners = (tuple(command) for runner in test_runners() for command in runner.get("commands") or [])
    return tuple(dict.fromkeys((*own, *runners)))


async def run_pre_tool_use(
    db: AsyncSession, *, session: Session, policy: Any, hook_input: dict[str, Any]
) -> tuple[ToolDecision | None, dict[str, Any]] | None:
    """``(denial or None, contract)`` for a run-bound session, ``None`` for any other."""
    from ...exec_policy import get_effective_exec_policy_config
    from .scm_rules import scm_hosts
    from .tool_policy import run_tool_decision

    run = await active_run_for_session(db, session.id)
    if run is None:
        return None
    if facts_change(run, hook_input.get(FACTS_KEY), session=session):
        # Claimed only when the facts change the run: a busy session never competes with the engine for nothing.
        run = await lock_run(db, run)
        record_facts(run, hook_input[FACTS_KEY], session=session)
    contract = await run_contract(db, run, principal=await session_principal(db, session), session=session)
    if isinstance(contract.get("phase"), dict) and contract["phase"].get("agent") is None:
        # A phase whose agent cannot run it (none named, retired, ceiling below the class) runs
        # nothing on a device either — the same rule as a chat turn's held resolution.
        return ToolDecision("deny", "needs_configuration", "phase_agent_unavailable", None,
                            "The run's phase has no agent that may run it; an admin publishes a version whose phase "
                            "names its agent."), contract
    from ...work_role_model.commands import with_role_commands
    from ...work_role_model.effective import effective_permission

    # The person's work roles add their phase shell rules on top of the Workspace's Command safety.
    exec_config = with_role_commands(await get_effective_exec_policy_config(db, project_id=session.project_id),
                                     await effective_permission(db, session.user_id, session.project_id))
    from ...devices.device_runs_keys import device_runs_section, tool_defaults

    decision = run_tool_decision(
        run, contract, session, hook_input,
        exec_config=exec_config,
        hosts=await scm_hosts(db, session.project_id), test_prefixes=test_prefixes(policy),
        defaults=tool_defaults(device_runs_section(getattr(policy, "raw", None) or {})))
    if decision is None or decision.decision == "allow":
        from ..run_memory import denial_answered

        try:  # what worked after a refusal, for the app's next run (run memory); never in the decision's way
            async with db.begin_nested():
                await denial_answered(db, run, hook_input)
        except Exception:  # noqa: BLE001
            logger.warning("run_memory_capture_failed", exc_info=True)
    return decision, contract


async def session_contract(db: AsyncSession, session: Session) -> dict[str, Any] | None:
    run = await active_run_for_session(db, session.id)
    if run is None:
        return None
    return await run_contract(db, run, principal=await session_principal(db, session), session=session)


__all__ = ["run_pre_tool_use", "session_contract", "test_prefixes"]
