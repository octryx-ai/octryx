"""The Stop's own check results: code style, how the tests ran (advisory before a pipeline), questions, items."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ToolCall, WorkflowRun
from .stop_evidence import _since

# The checks that judge how the agent ran its tests. Before a pipeline step they are advisory: the pipeline runs the
# declared commands itself and is the one judge of green and of each task's proof. Blocking, they caused (Claude
# Haiku, benchmark runs) 34 Stop refusals in 7 stories over the agent's own runs (the declared suite not run verbatim
# after the last edit, the system test command not verbatim, proof tests not recognised as added or extended in the
# diff), 5 human interventions, 3 hotfixes for proof detection, and the agent stopping "because the stop hook keeps
# blocking". Code limits and every other check stay blocking.
TEST_CHECK_TYPES = frozenset({"test_command_passed"})
TEST_TOOLS = frozenset({"run_test_suite"})


def advisory_test_checks(checks: list[Any]) -> list[Any]:
    """``checks`` with the test checks non-blocking: ``test_command_passed`` and a ``tool_called`` that asks only for
    the test suite tool."""
    def about_tests(check: dict[str, Any]) -> bool:
        if check.get("type") in TEST_CHECK_TYPES:
            return True
        tools = {str(tool) for tool in dict(check.get("params") or {}).get("tools") or []}
        return check.get("type") == "tool_called" and bool(tools) and tools <= TEST_TOOLS

    return [{**check, "blocking": False} if isinstance(check, dict) and about_tests(check) else check
            for check in checks]


RED_CHECK = "tests_red"


def expects_red(graph: Any, node_id: str) -> bool:
    """A phase whose result a ``tests_red`` gate judges (TDD "Tests first"): its suite ends red by design, so the
    full-suite check does not apply to it."""
    for gate in dict(getattr(graph, "nodes", None) or {}).values():
        config = dict(getattr(gate, "config", None) or {})
        if config.get("phase") == node_id and any(isinstance(check, dict) and check.get("type") == RED_CHECK
                                                 for check in config.get("checks") or []):
            return True
    return False


def _record_knowledge_usage(db: AsyncSession, run: WorkflowRun, tool_calls: Sequence[ToolCall]) -> None:
    """The phase's knowledge and web lookups as run event ``knowledge_usage`` (knowledge-first principle),
    when it made any."""
    from ...observability.knowledge_metrics import phase_usage
    from ..records import record_event

    usage = phase_usage(tool_calls, _since(run))
    if any(usage.values()):
        record_event(db, run, "knowledge_usage", node_id=run.current_node_id, detail=usage)


def _story_contract_gap(run: WorkflowRun, node: Any, change: Any) -> Any:
    """The coordinator's plan pass: the contract sections its items cite exist in the contract it wrote
    (``teamwork.contract_gate``)."""
    from ..phase_outputs import phase_output
    from ..teamwork import OUTPUT_KIND
    from ..teamwork.contract_gate import contract_gap_result

    return contract_gap_result(run, change) if phase_output(node) == OUTPUT_KIND else None


_NUMBERED = re.compile(r"^\s*(?:[#>*-]+\s*)?(?:\*\*)?(?:Q\s*)?\d{1,2}[.):](?:\*\*)?\s+\S", re.MULTILINE)


def _questions_missing(answer: str) -> list[Any]:
    """A question round whose answer asks nothing: blocking (otherwise an interview that
    answered only "I can't read the run contract" passed and waited for the product owner's answers to no question).
    At least one numbered question (``1.``, ``2)``, ``Q3:``) is asked for; "no question needed" is a numbered
    proposal too, so a round never passes empty."""
    from ...workflow_checks.library import FAILED, CheckResult

    if _NUMBERED.search(answer or ""):
        return []
    return [CheckResult(type="questions_asked", outcome=FAILED, blocking=True,
                        description="The question round asks the product owner numbered questions, each with a "
                                    "proposed answer", detail="the answer holds no numbered question")]


def _item_result_missing(run: WorkflowRun, key: str) -> list[Any]:
    """An item's Stop before it recorded ``done`` or ``blocked``: the Stop blocks and names the result tool, instead
    of the item failing at once with "it ended without recording done or blocked" (a small model often stops first
    and records after the reminder)."""
    from ...workflow_checks.library import FAILED, CheckResult
    from ..teamwork import ITEM_RESULT_VALUES, work_of

    item = dict(dict(work_of(run).get("items") or {}).get(key) or {})
    if dict(item.get("result") or {}).get("value") in ITEM_RESULT_VALUES:
        return []
    return [CheckResult(type="item_result", outcome=FAILED, blocking=True,
                        description='Finish the item with submit_phase_result "done" (or "blocked" with the reason)',
                        detail="")]


def _advisory(result: Any) -> Any:
    from dataclasses import replace

    return replace(result, blocking=False)


def _code_style_results(db: AsyncSession, run: WorkflowRun, contract: dict[str, Any], facts: dict[str, Any],
                        results: list[Any]) -> list[Any]:
    """The code style over the change's sizes; its warnings kept on the run."""
    from .code_limits import style_result

    phase = dict(contract.get("phase") or {})
    limited = style_result(phase.get("code_style"), facts.get("sizes"), facts.get("style_tools"), facts.get("l10n"),
                           facts.get("diagrams"))
    if limited is not None:
        results = [*results, limited]
    if limited is not None and limited.detail and phase.get("code_style"):
        # the style's warnings (a missing tool with how to install it, a touched legacy file) reach
        # the run's timeline and the next phase's agent (``phase_contract``: code_style_warnings).
        from ..records import record_event

        record_event(db, run, "code_style_warnings", node_id=run.current_node_id, detail={"warnings": limited.detail})
        run.context = {**dict(run.context or {}), "code_style_warnings": limited.detail[:2000]}
    from ...code_style.diagrams import reviewer_notes

    if notes := reviewer_notes(facts.get("diagrams")):  # the reviewer checks the boxes no code name matched
        run.context = {**dict(run.context or {}), "diagram_notes": notes[:20]}
    return results


def _test_results(run: WorkflowRun, graph: Any, node: Any, contract: dict[str, Any], tool_calls: Sequence[ToolCall],
                  facts: dict[str, Any], results: list[Any], *, piped: bool, item: Any, delegates: bool) -> list[Any]:
    """How the agent ran its tests: the system tests, the declared suite and the task list's proofs."""
    from .system_tests import system_tests_result

    phase_system = dict(dict(contract.get("phase") or {}).get("system_tests") or {})
    # Left to the pipeline: no check, not even advisory, asks the agent to run it.
    system = None if phase_system.get("by_pipeline") else system_tests_result(
        phase_system or None, tool_calls, _since(run), change=facts.get("change"))
    if system is not None:
        results = [*results, _advisory(system) if piped else system]
    from ..size_class.pipeline_scope import agent_runs_system_test
    from .declared_suite import declared_suite_result

    # The full suite after the last change blocks every phase that changes code (when it was
    # advisory before a pipeline, implement ended on single files and the pipeline went red loop after loop); before
    # a pipeline it covers the system test command too. A teamwork item builds one part: advisory there.
    suite = None if expects_red(graph, node.id) else declared_suite_result(
        contract, tool_calls, _since(run), change=facts.get("change"),
        keys=("test", "system_test") if piped and agent_runs_system_test(run) else ("test",))
    if suite is not None:
        # A story session (epic-delivery: the phase delegates to its own sub-agents) ends when its agent says done; the
        # pipeline right after it is the judge and sends red back into the same session. Otherwise
        # a blocking suite check refused its Stop three times over system tests its sandbox could not run
        # (the pipeline runs them outside it) and paused the run runtime_failed.
        from ..size_class.tests_scope import AFFECTED, agent_tests, pipeline_later

        # Lever 1: a class whose agent runs the affected tests only leaves the whole suite to the
        # pipeline after the phase, gates between them included (the schema allows it only with one).
        relaxed = item is not None or (piped and delegates) or (
            agent_tests(run) == AFFECTED and pipeline_later(graph, node.id))
        results = [*results, _advisory(suite) if relaxed else suite]
    from ..task_list import passed_tests, task_list_result

    listed = task_list_result(list(dict(contract.get("phase") or {}).get("task_list") or []), facts.get("change"),
                              passed_tests(run))
    if listed is not None:
        results = [*results, _advisory(listed) if piped else listed]
    return results
