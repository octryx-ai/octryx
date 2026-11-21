"""Stop / SubagentStop of a run-bound octryx-claude session: submit the evidence, the server decides.

The launcher's Stop hook asks the server (``POST sessions/verification``). For a session bound to a workflow run,
the run's current phase decides instead of the Workspace test gate:

1. the run is claimed; the launcher's facts (confirmed test digests, the change) are recorded (``facts``);
2. the evidence is the session's own recorded tool calls since the phase was entered — the gateway records every
   tool call the model made, so the device's word is not needed: platform MCP tools by name, a Bash test command
   (the Workspace's ``test_command_prefixes``) as ``run_test_suite`` with its result only when its runner executed
   tests (``test_command_outcome``; a runner that could not start pauses the run ``environment_not_ready`` through
   ``binding.record_phase_turn``, no loop consumed), edits as changes, Claude
   Code's own reads (Read, Grep, Glob, LS) as the platform read tools when the server recorded them inside the
   bound repository (``agent_gateway/read_evidence``); a phase that checks citations gets the counts of the
   observed answer against the platform's sources (``citations``);
3. the phase's checks are evaluated (before a CI pipeline step, ``pipeline_after`` in the phase contract, the checks
   of how the agent ran its tests are advisory: :data:`TEST_CHECK_TYPES`, the declared suite, the system tests and
   the task proofs — the pipeline judges them) and the result is reported to the run like a chat phase turn
   (``binding.record_phase_turn`` with this pass's marker): **only the server advances** — a passed phase goes on
   to its gate, a failed gate loops back within *n*, at *n* the run pauses;
4. the answer: ``blocked`` with the phase's missing checks while the phase is not done (the launcher's block cap
   applies; the run simply stays in the phase), else ``passed``; a paused or waiting run lets the session end and
   says why (the decision is the platform's). Every answer carries the refreshed contract.

**SubagentStop** reports one child: the phase's checks over the tool calls that sub-agent made (attributed by
Claude Code's ``agent_id`` at PostToolUse), recorded per child on the run (``context.octryx_children``); it blocks the
child while its checks fail and never advances the run — only the main session's Stop does. In a phase that opted in
to sub-agents (``config.subagents: true``, ``octryx.subagents``) the child is recorded but never blocked: the main
session hands it a part (find the callers, write one module), not the phase, and the main Stop still judges the phase
over every tool call of the session, the children's included.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, ToolCall, WorkflowRun
from ...workflow_checks.library import TurnEvidence, evaluate_checks, failed_blocking
from ..records import active_run_for_session, lock_run
from ..run_texts import run_text
from ..states import PAUSE_ENVIRONMENT_NOT_READY, PAUSE_EVIDENCE_UNRESOLVED, STATUS_PAUSED, STATUS_RUNNING
from .child_stop import _child_stop
from .contract import contract_summary, run_contract, session_principal
from .facts import FACTS_KEY, record_facts
from .stop_answers import _answers_since, _keep_task_list, _last_answer, phase_answer, question_round_phase
from .stop_checks import (
    _code_style_results,
    _item_result_missing,
    _questions_missing,
    _record_knowledge_usage,
    _story_contract_gap,
    _test_results,
    advisory_test_checks,
)
from .stop_evidence import _since, declared_lint, phase_evidence, written_files
from .stop_stall import _item_stalled, _set_item_stall, _set_stall, _stalled

REASON_PHASE_NOT_DONE = "workflow_phase_checks_failed"
REASON_RUN_NOT_AT_PHASE = "workflow_run_not_at_phase"
REASON_COORDINATOR_WAKE = "teamwork_coordinator_wake"
REASON_RUN_PAUSED = "workflow_run_paused"
REASON_ITEM_NOT_RUNNING = "teamwork_item_not_running"


async def run_stop(
    db: AsyncSession, *, session: Session, hook_input: dict[str, Any], tool_calls: Sequence[ToolCall],
    test_prefixes: tuple[tuple[str, ...], ...],
) -> dict[str, Any] | None:
    """The Stop answer of a run-bound session, or ``None`` when the session follows no run."""
    from ..graph import graph_for_run

    run = await active_run_for_session(db, session.id)
    if run is None:
        return None
    run = await lock_run(db, run)
    record_facts(run, hook_input.get(FACTS_KEY), session=session)
    principal = await session_principal(db, session)
    contract = await run_contract(db, run, principal=principal, session=session)
    if (ended := _not_at_phase(run, contract)) is not None:
        return ended
    graph = await graph_for_run(db, run)
    node = graph.nodes[run.current_node_id]
    from ..teamwork.item_sessions import item_phase_node, session_item
    from .subagents import node_allows_subagents

    delegates = node_allows_subagents(node)  # the run's own node decides, as for the job offer

    item = session_item(run, session)  # running at the parallel node (an idle item's session returned above)
    if item is not None:
        node = item_phase_node(run, node, item)  # a teamwork item's Stop is judged by its own phase
    if str(hook_input.get("hook_event_name") or "") == "SubagentStop":
        return await _child_stop(db, run, node, hook_input, tool_calls, test_prefixes, principal=principal,
                                 session=session, delegates=delegates)
    evidence, checks, piped = await _phase_checks(db, run, session, node, contract, hook_input, tool_calls,
                                                  test_prefixes, item=item)
    results = evaluate_checks(checks, evidence)
    facts = hook_input.get(FACTS_KEY) if isinstance(hook_input.get(FACTS_KEY), dict) else {}
    results = _code_style_results(db, run, contract, facts, results)
    results = _test_results(run, graph, node, contract, tool_calls, facts, results, piped=piped, item=item,
                            delegates=delegates)
    if item is not None and not failed_blocking(results):
        results = [*results, *_item_result_missing(run, item["id"])]
    if item is None and (gap := _story_contract_gap(run, node, facts.get("change"))) is not None:
        results = [*results, gap]  # blocking even before a pipeline: no item may start on a contract with holes
    answer = await _last_answer(db, session.id, _since(run), hook_input)
    if item is None and question_round_phase(node):
        answer = phase_answer(run, node.id, None, answer)
        results = [*results, *_questions_missing(answer)]
    failed = failed_blocking(results)
    from .. import uncertain

    uncertain.note_results(db, run, results, source="stop")  # passed although unsure: a note, no block
    if item is None and not failed:
        _record_knowledge_usage(db, run, tool_calls)
    await _report_turn(db, run, session, node, item, evidence, results, answer, facts=facts, failed=failed,
                       piped=piped)
    return await _stop_answer(db, run, session, node, item, tool_calls, hook_input, checks, failed,
                              principal=principal)


def _not_at_phase(run: WorkflowRun, contract: dict[str, Any]) -> dict[str, Any] | None:
    """The answer for a session whose Stop ends no phase pass: an idle item, a coordinator wake, no running phase."""
    if contract.get("item_idle"):
        # A teamwork item's session never answers for the run's phase: its item no longer runs, it ends here.
        return {"state": "not_applicable", "reason": REASON_ITEM_NOT_RUNNING, "detail": contract_summary(contract),
                "workflow_run": contract}
    if dict(contract.get("phase") or {}).get("coordinator_wake"):
        # The coordinator answered the board while its items run (teamwork): no phase pass ends here.
        return {"state": "not_applicable", "reason": REASON_COORDINATOR_WAKE, "detail": contract_summary(contract),
                "workflow_run": contract}
    if run.status != STATUS_RUNNING or contract.get("phase") is None:
        return {"state": "not_applicable", "reason": REASON_RUN_NOT_AT_PHASE, "detail": contract_summary(contract),
                "workflow_run": contract}
    return None


async def _phase_checks(db: AsyncSession, run: WorkflowRun, session: Session, node: Any, contract: dict[str, Any],
                        hook_input: dict[str, Any], tool_calls: Sequence[ToolCall],
                        test_prefixes: tuple[tuple[str, ...], ...], *, item: Any) -> tuple[TurnEvidence, list, bool]:
    """The phase's evidence and checks: ``(evidence, checks, a pipeline step follows the phase)``."""
    from .system_tests import system_command

    evidence = phase_evidence(tool_calls, since=_since(run), test_prefixes=test_prefixes,
                              checks=declared_lint(contract), system=system_command(contract))
    from .research import research_phase_definition

    # The Workspace's research switch adds its checks at runtime, also to a run pinned to an older version.
    checks = list(dict((await research_phase_definition(db, run, node)).get("workflow_contract") or {}).get(
        "checks") or [])
    piped = bool(dict(contract.get("phase") or {}).get("pipeline_after"))
    if piped:
        checks = advisory_test_checks(checks)
    if any(isinstance(check, dict) and check.get("type") == "citations_present" for check in checks):
        from .citations import citation_counts

        evidence.cited_count, evidence.source_count = await citation_counts(db, session.id, tool_calls,
                                                                            since=_since(run))
    if any(isinstance(check, dict) and check.get("type") == "urls_cited" for check in checks):
        evidence.written_files = written_files(run, hook_input)
    from ..workspace.empty_copy import asks_for_reads, device_copy_empty

    if item is None and asks_for_reads(checks):
        # An empty repository: nothing a read can succeed on.
        evidence.workspace_empty = await device_copy_empty(run, db)
    return evidence, checks, piped


async def _report_turn(db: AsyncSession, run: WorkflowRun, session: Session, node: Any, item: Any,
                       evidence: TurnEvidence, results: list[Any], answer: Any, *, facts: dict[str, Any],
                       failed: list[Any], piped: bool) -> None:
    """Report the phase turn to the run like a chat phase turn (only the server advances)."""
    from ...workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
    from ..binding import record_phase_turn
    from ..states import RUN_RESOLUTION_KEY

    marker = {"run_id": run.id, "node_id": node.id, "kind": run.workflow_kind,
              "entry": dict(run.node_state or {}).get("entry"), **({"item": item["id"]} if item is not None else {})}
    if item is None:
        # With a pipeline after the phase, the pipeline sets ``done`` (its proof passed there); the Stop only moves
        # tasks to ``in_progress`` by the change. An item's change is its worktree's, never the story's task state.
        await _keep_task_list(db, run, node, answer, change=facts.get("change"), passed=not failed and not piped)
    # The test runs were recorded on the run already (``gateway_tests``); the turn reports the phase result only.
    reported = TurnEvidence(tools=evidence.tools, verification_state=evidence.verification_state,
                            cited_count=evidence.cited_count, source_count=evidence.source_count,
                            environment_failure=evidence.environment_failure, answer=answer)
    unresolved = any(getattr(result, "unresolved", False) and getattr(result, "blocking", False)
                     for result in results)
    if item is None or not failed or evidence.environment_failure or unresolved:
        await record_phase_turn(db, request_analysis={ROUTING_RESOLUTION_KEY: {RUN_RESOLUTION_KEY: marker}},
                                session_id=session.id, state="failed" if failed else "passed", results=results,
                                evidence=reported)
    # Else an item's Stop with failing checks: no end of the item — the answer blocks and its agent goes on (live
    # example: core-domain was marked failed at its first Stop, attempts 1, while its job kept
    # working; with the other item failed the node went back to the plan under it). The item ends when a Stop
    # passes, when it stalls (``_item_stalled``) or when its turn really ends (``device_items.job_ended``).


async def _stop_answer(db: AsyncSession, run: WorkflowRun, session: Session, node: Any, item: Any,
                       tool_calls: Sequence[ToolCall], hook_input: dict[str, Any], checks: list[Any],
                       failed: list[Any], *, principal: Any) -> dict[str, Any]:
    """The answer to the Stop hook with the refreshed contract: ended, blocked with what is missing, or passed."""
    contract = await run_contract(db, run, principal=principal, session=session)
    if contract.get("item_idle") and failed:
        # The item ended on this report (its environment could not run the tests): the session ends.
        return {"state": "not_applicable", "reason": REASON_ITEM_NOT_RUNNING, "detail": contract_summary(contract),
                "workflow_run": contract}
    if run.status == STATUS_PAUSED and run.pause_reason in (PAUSE_ENVIRONMENT_NOT_READY, PAUSE_EVIDENCE_UNRESOLVED):
        # The run paused on this report (the environment could not run the tests, or the platform could not match
        # their evidence): the session ends, nothing loops.
        return {"state": "not_applicable", "reason": REASON_RUN_PAUSED, "detail": contract_summary(contract),
                "workflow_run": contract}
    if failed:
        return await _blocked(db, run, session, node, item, tool_calls, checks, failed, contract,
                              principal=principal)
    if item is None:
        _set_stall(run, None)
    else:
        _set_item_stall(run, item["id"], None)
    from .same_turn import STATE_NEXT_PHASE, continue_in_turn

    if item is None and (prompt := await continue_in_turn(db, run, hook_input)):
        contract = await run_contract(db, run, principal=principal, session=session)
        return {"state": STATE_NEXT_PHASE, "reason": "workflow_phase_changed", "detail": prompt,
                "workflow_run": contract}
    return {"state": "passed", "reason": "workflow_phase_reported", "detail": contract_summary(contract),
            "workflow_run": contract}


async def _blocked(db: AsyncSession, run: WorkflowRun, session: Session, node: Any, item: Any,
                   tool_calls: Sequence[ToolCall], checks: list[Any], failed: list[Any], contract: dict[str, Any], *,
                   principal: Any) -> dict[str, Any]:
    """The phase is not done: block with each failed check and what to do, unless the pass stalled (paused)."""
    from ...observability.agent_metrics import on_commit
    from ...observability.run_quality_metrics import stop_not_done
    from .check_remedies import missing as with_remedies

    # Each failed check with what to do about it (``check_remedies``, run.remedy.<type>).
    missing = with_remedies(failed, checks, contract)
    workflow, refused = str(run.workflow_key or ""), list(failed)
    on_commit(db, lambda: stop_not_done(workflow, refused))  # "not done" by check type (counted at the commit)
    since = _since(run)
    attempts = sum(1 for row in tool_calls if since is None or row.created_at is None or row.created_at >= since)
    attempts += await _answers_since(db, session.id, since)
    stalled = await _stalled(db, run, node.id, missing, attempts) if item is None else await _item_stalled(
        db, run, item["id"], session.id, missing, attempts)
    if stalled:
        contract = await run_contract(db, run, principal=principal, session=session)
        return {"state": "not_applicable", "reason": REASON_RUN_PAUSED, "detail": contract_summary(contract),
                "workflow_run": contract}
    from .gate_failure import stop_line

    back = stop_line(run, node.id)  # why the run is back here, first
    return {"state": "blocked", "reason": REASON_PHASE_NOT_DONE, "workflow_run": contract,
            "detail": f"{back + ' ' if back else ''}" + run_text(
                "block.phase_not_done", phase=node.title, detail=missing, run_state=contract_summary(contract))}


__all__ = ["REASON_PHASE_NOT_DONE", "REASON_RUN_NOT_AT_PHASE", "REASON_RUN_PAUSED", "run_stop"]
