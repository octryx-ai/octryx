"""A gate node: deterministic checks over the recorded evidence decide its route value."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from ..workflow_checks.evidence_families import alert_gate_scope
from ..workflow_checks.library import FAILED as CHECK_FAILED
from ..workflow_checks.library import NOT_APPLICABLE, ToolUse, TurnEvidence, evaluate_checks, unresolved_blocking
from .engine_context import _WAIT, _context, _set_context
from .graph import FAILED, PASSED, PhasedNode
from .limits import pause_run
from .records import record_event
from .states import EVENT_GATE
from .test_runs import gate_fields


def _gate_evidence(run: WorkflowRun, node: PhasedNode) -> tuple[str, TurnEvidence]:
    context = _context(run)
    phase_id = str(node.config.get("phase") or context.get("last_phase") or "")
    recorded = dict(dict(context.get("evidence") or {}).get(phase_id) or {})
    tools = [ToolUse(str(item.get("name") or ""), bool(item.get("succeeded"))) for item in recorded.get("tools") or []]
    evidence = TurnEvidence(
        tools=tools, artifacts=[{"type": item} for item in recorded.get("artifacts") or []],
        cited_count=recorded.get("cited_count"), source_count=recorded.get("source_count"),
        verification_state=recorded.get("verification_state"), **gate_fields(run),
        review=_fresh_review(run, phase_id),
        # The phase's evidence family records, judged against the run's alert target and window.
        evidence_records=list(recorded.get("evidence_records") or []), alert_scope=alert_gate_scope(run),
    )
    return phase_id, evidence


def _fresh_review(run: WorkflowRun, phase_id: str) -> dict[str, Any] | None:
    review = dict(_context(run).get("review") or {})
    turn = dict(dict(run.gate_results or {}).get(phase_id) or {})
    if not review or str(review.get("at") or "") < str(turn.get("at") or ""):
        return None
    return review


# Checks whose "not applicable" means no test evidence: an all-unjudged gate of these still fails.
TEST_EVIDENCE_TYPES = frozenset({"tests_red", "tests_green", "confirmed_tests_intact", "reproduces",
                                 "test_command_passed"})


#: Checks whose failure detail the platform writes itself (test runs, lint, CI, tool calls): safe for every reader.
OWN_WORDS = frozenset({"tests_red", "tests_green", "confirmed_tests_intact", "reproduces", "ci_green",
                       "test_command_passed", "tool_called", "tool_not_called"})


async def _evaluate_gate(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> Any:
    # A gate none of whose blocking checks could be judged fails; unjudgeable evidence pauses instead of using a round.
    phase_id, evidence = _gate_evidence(run, node)
    checks = list(node.config.get("checks") or [])
    if not await _gather_gate_evidence(db, run, node, checks, evidence):
        return _WAIT
    results = evaluate_checks(checks, evidence)
    blocking = [result for result in results if result.blocking]
    judged = [result for result in blocking if result.outcome != NOT_APPLICABLE]
    failed = [result for result in judged if result.outcome == CHECK_FAILED]
    if failed and all(getattr(result, "unresolved", False) for result in failed):
        from .evidence_pause import deferred_to_pipeline

        if await deferred_to_pipeline(db, run, failed, node_id=node.id):
            failed = []  # the pipeline after this gate judges the tests from its own report
    source_missing = not phase_id and evidence.review is None
    # Fail open: a gate none of whose blocking checks could be judged (all not applicable:
    # no CI result yet) passes with a ``check_uncertain`` note instead of looping the agent.
    # A gate no phase ran before (and no artefact review feeds) has no evidence source at all: it stays failed.
    # Test evidence stays a finding (a green gate that judged no test run must not pass):
    # only gates whose unjudged checks need outside evidence (CI, citations) fail open.
    unjudged = bool(blocking) and not judged and not any(item.type in TEST_EVIDENCE_TYPES for item in blocking)
    value = FAILED if failed or source_missing or (blocking and not judged and not unjudged) else PASSED
    _record_gate(db, run, node, phase_id, value, results, failed)
    _note_gate(db, run, node, phase_id, value, results, blocking, failed, unjudged=unjudged)
    if value == FAILED and (unresolved := unresolved_blocking(results)):
        from .evidence_pause import pause_unresolved

        await pause_unresolved(db, run, unresolved, node_id=node.id)
        return _WAIT
    return value


async def _gather_gate_evidence(db: AsyncSession, run: WorkflowRun, node: PhasedNode, checks: list[Any],
                                evidence: TurnEvidence) -> bool:
    if any(check.get("type") == "specification_ready" for check in checks):
        from .specification.integration import readiness_states
        from .states import PAUSE_NEEDS_CONFIGURATION

        evidence.specification = await readiness_states(db, run, checks)
        if any(value.get("state") == "needs_configuration" for value in evidence.specification.values()):
            await pause_run(db, run, reason=PAUSE_NEEDS_CONFIGURATION, actor_id=None, detail={
                "message": "The specification source bindings changed; restore access or revise the record.",
                "resume": {"kind": "restart", "node_id": node.id}})
            return False
    if any(check.get("type") == "artefact_review_passed" for check in checks):
        from .review.artefact_gate import gate_record

        evidence.review = await gate_record(db, run, node)
    return True


def _record_gate(db: AsyncSession, run: WorkflowRun, node: PhasedNode, phase_id: str, value: Any,
                 results: list[Any], failed: list[Any]) -> None:
    gate = {"state": value, "phase": phase_id or None, "results": [result.as_dict() for result in results],
            "at": utc_now().isoformat()}
    run.gate_results = {**dict(run.gate_results or {}), node.id: gate}
    _set_context(run, "results", node.id, value)
    # a failed gate's event says which checks failed and why (not only "failed").
    # Only the platform's own words: a review check's detail quotes sources a viewer may not read (it stays in
    # ``run.gate_results``, behind the run's access rules).
    record_event(db, run, EVENT_GATE, node_id=node.id, detail={
        "state": value, "phase": phase_id or None,
        **({"failed": [{"type": item.type, **({"detail": str(item.detail or "")[:300]} if item.type in OWN_WORDS
                                               else {"detail_withheld": True})} for item in failed[:10]]}
           if value == FAILED else {})})


def _note_gate(db: AsyncSession, run: WorkflowRun, node: PhasedNode, phase_id: str, value: Any, results: list[Any],
               blocking: list[Any], failed: list[Any], *, unjudged: bool) -> None:
    from . import uncertain

    if unjudged and value == PASSED:
        uncertain.note(db, run, control=f"gate:{node.id}", node_id=node.id, reason=(
            "no blocking check could be judged: " + "; ".join(f"{item.type} ({item.detail})" for item in blocking)))
    uncertain.note_results(db, run, results, source=f"gate:{node.id}")
    from .octryx import gate_failure

    if value == FAILED and phase_id:
        gate_failure.record(run, gate=node.title or node.id, phase=phase_id,
                            failed=failed or [result for result in blocking if result.outcome == NOT_APPLICABLE])
    else:
        gate_failure.clear(run)
