"""SubagentStop: one Claude Code sub-agent's report, its own evidence for the phase recorded per child."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ToolCall, WorkflowRun
from ....time_utils import utc_now
from .contract import contract_summary, run_contract
from .stop_evidence import _parameters, _since, declared_lint, phase_evidence


async def _child_stop(db: AsyncSession, run: WorkflowRun, node: Any, hook_input: dict[str, Any],
                      tool_calls: Sequence[ToolCall], test_prefixes: tuple[tuple[str, ...], ...], *,
                      principal: Any = None, session: Any = None, delegates: bool = False) -> dict[str, Any]:
    """One Claude Code sub-agent's report: its own evidence for the phase, recorded per child; no advance.

    ``delegates``: the phase opted in to sub-agents, so a child with missed checks is recorded ``failed`` but not
    blocked; the main session's Stop judges the phase."""
    from ...workflow_checks.library import FAILED
    from ...workflow_checks.library import evaluate_checks as evaluate
    from ..records import record_event
    from .research import research_phase_definition
    from .stop import REASON_PHASE_NOT_DONE

    agent_id = str(hook_input.get("agent_id") or "")[:80] or "subagent"
    own = [row for row in tool_calls if _parameters(row).get("agent_id") == agent_id]
    evidence = phase_evidence(own, since=_since(run), test_prefixes=test_prefixes,
                              checks=declared_lint(await run_contract(db, run, principal=principal, session=session)))
    checks = list(dict((await research_phase_definition(db, run, node)).get("workflow_contract") or {}).get(
        "checks") or [])
    missed = [result.description or result.type for result in evaluate(checks, evidence)
              if result.blocking and result.outcome == FAILED]
    children = dict(dict(run.context or {}).get("octryx_children") or {})
    children[agent_id] = {"node_id": node.id, "entry": dict(run.node_state or {}).get("entry"),
                          "state": "failed" if missed else "passed", "missed_checks": missed[:20],
                          "tool_calls": len(own), "at": utc_now().isoformat()}
    run.context = {**dict(run.context or {}), "octryx_children": children}
    record_event(db, run, "subagent_reported", node_id=node.id,
                 detail={"agent_id": agent_id, "state": children[agent_id]["state"]})
    contract = await run_contract(db, run, principal=principal, session=session)
    if missed and not delegates:
        return {"state": "blocked", "reason": REASON_PHASE_NOT_DONE, "workflow_run": contract,
                "detail": f"This sub-agent's part of phase '{node.title}' is not done: {'; '.join(missed)}."}
    return {"state": "passed", "reason": "subagent_reported", "detail": contract_summary(contract),
            "workflow_run": contract}
