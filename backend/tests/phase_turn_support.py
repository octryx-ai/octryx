"""A phase turn that ended with these tool calls: the platform judges its workflow checks and reports the result to
the run, as a runner's turn end does (``evaluate_checks`` → ``record_phase_turn``), without an agent loop."""

from __future__ import annotations

from typing import Any

from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
from app.services.workflow_checks.evidence import turn_evidence
from app.services.workflow_checks.library import evaluate_checks, workflow_checks
from app.services.workflow_checks.results import RUNTIME_CHAT, check_state, store_check_result
from app.services.workflow_checks.steps import step_checks
from app.services.workflow_checks.test_results import DEFAULT_TEST_PREFIXES
from app.services.workflow_routing.workflow_selection import (
    ROUTING_RESOLUTION_KEY,
    workflow_selection_from_resolution,
)
from app.services.workflow_runs.binding import record_phase_turn


async def finish_phase_turn(db, session_id: str, resolution: dict[str, Any], history: list[dict[str, Any]], *,
                            content: str = "Done.", answer_evidence: dict[str, Any] | None = None) -> str | None:
    if not workflow_selection_from_resolution(resolution).selected:
        return None
    contract = resolution.get("workflow_contract")
    checks = [*workflow_checks(contract), *step_checks(contract)]
    if not checks:
        return None
    request_analysis = {ROUTING_RESOLUTION_KEY: resolution}
    evidence = turn_evidence(history, answer=content, answer_evidence=answer_evidence,
                             test_command_prefixes=DEFAULT_TEST_PREFIXES)
    with prompt_set_scope(seed_prompt_set()):
        from app.services.workflow_runs.ci_return import with_ci_fix
        from app.services.workflow_runs.workspace.empty_copy import asks_for_reads, turn_workspace_empty

        if any(check.get("type") == "evidence_families" for check in checks):
            from app.services.workflow_checks.evidence_families import session_gate_scope

            evidence.alert_scope = await session_gate_scope(db, session_id)
        if asks_for_reads(checks):
            evidence.workspace_empty = await turn_workspace_empty(db, request_analysis=request_analysis)
        checks = await with_ci_fix(db, checks, evidence, request_analysis=request_analysis)
        results = evaluate_checks(checks, evidence)
        state = check_state(results)
        await store_check_result(db, session_id=session_id, trace_id=None,
                                 workflow_key=str(resolution.get("workflow_key") or ""), workflow_version=None,
                                 runtime=RUNTIME_CHAT, state=state, results=results)
        await record_phase_turn(db, request_analysis=request_analysis, session_id=session_id, state=state,
                                results=results, evidence=evidence)
    await db.commit()
    return state


__all__ = ["finish_phase_turn"]
