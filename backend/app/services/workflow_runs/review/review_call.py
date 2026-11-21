"""One review call: the reviewer's task and rules, the model's answer, and the platform's gates on the verdict."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .answer_checks import RETRY_RULE, _reviewed_phase_protects_tests, _settle, look_floor, root_cause_gate
from .call_inputs import _review_model, _screens, _working_copy
from .convergence import FOLLOW_UP_RULE, Scope, follow_up_task, previous_findings
from .model import ReviewModelUnavailableError
from .reading import NOTES_KEY, SCREENS_RULE, _answer_with_screens, _summed, _two_stage_spec_review, read_in_parts
from .verdict import (
    ACCEPTANCE_FOLLOW_UP,
    ACCEPTANCE_RULE,
    ANSWER_CONTRACT,
    ASSUMPTIONS_RULE,
    CONFIRMED_CONTRACT_RULE,
    PO_ANSWERS_RULE,
    ROOT_CAUSE_RULE,
    SCOPE_RULE,
    SEVERITY_RULE,
    SPEC_DECISIONS_RULE,
    SPEC_IDENTIFIER_RULE,
    SPEC_REVIEW_RULE,
    SUGGESTION_RULE,
    WALKTHROUGH_RULE,
)

ModelFactory = Callable[..., Awaitable[Any]]


async def _ask(db: AsyncSession, run: WorkflowRun, model_factory: ModelFactory
               ) -> tuple[Any, Any, str, str, dict[str, Any]]:
    """``(verdict, usage, reason, tree, reviewer facts)``; a verdict of ``None`` means no decision (with ``reason``).

    Nothing to review (no change for this pass) is no decision either: the model is not asked."""
    from ..graph import graph_for_run
    from .artefact_contract import is_artefact
    from .evidence import review_task
    from .reviewer_agent import reviewer_setup

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if is_artefact(node):
        from .artefact_runner import ask

        return await ask(db, run, node, model_factory)
    review = await review_task(db, run)
    if not review.has_change:
        return None, None, f"no_change: {review.no_change}", "", {}
    setup = await reviewer_setup(db, run)
    if isinstance(setup, str):
        return None, None, setup, review.tree, {}
    config = dict(node.config or {}) if node is not None else {}
    spec = config.get("checklist") == "spec"
    previous = previous_findings(run, node)
    system = f"{setup.instructions}\n{CONFIRMED_CONTRACT_RULE}"
    tests_protected = _reviewed_phase_protects_tests(await graph_for_run(db, run), run, config)
    system = _system_rules(system, config, review, spec=spec, tests_protected=tests_protected)
    if previous:
        import dataclasses

        follow = follow_up_task(previous)
        review = dataclasses.replace(review, task=f"{review.task}\n\n{follow}",
                                     frame=f"{review.frame}\n\n{follow}" if review.frame else "")
    decisions = None
    if not spec:
        review, system, decisions = await _with_spec_decisions(db, run, review, system)
    review, system = await _with_pipeline_needs(db, run, review, system, spec=spec)
    from .choice import review_choice

    choice = await review_choice(db, run, config)
    if isinstance(choice, str):
        return None, None, choice, review.tree, {}
    try:
        model, answered, settled, notes = await _ask_model(
            db, run, model_factory, setup, choice, review, config, system, previous=previous, spec=spec)
    except ReviewModelUnavailableError as error:
        return None, None, error.reason, review.tree, {}
    return _outcome(run, config, review, setup, choice, model, answered, settled, notes,
                    tests_protected=tests_protected, decisions=decisions)


def _system_rules(system: str, config: dict[str, Any], review: Any, *, spec: bool, tests_protected: bool) -> str:
    """The reviewer's system prompt with the rules the node's config, the answers and the task list ask for."""
    if tests_protected:
        from .tests_gate import TESTS_PROTECTED_RULE

        system = f"{system}\n{TESTS_PROTECTED_RULE}"
    # A follow-up answers its previous findings by id instead of giving a fresh verdict (``convergence``): its
    # contract replaces the first-round one and comes last, so no rule after it asks for a full audit again.
    system = (f"{system}\n{SPEC_REVIEW_RULE}\n{SPEC_IDENTIFIER_RULE}" if spec
              else f"{system}\n{SCOPE_RULE}\n{SEVERITY_RULE}")
    if config.get("assumptions") is True:
        system = f"{system}\n{ASSUMPTIONS_RULE}"
    if config.get("suggestions") is True:  # the PR review bot's inline suggestions (``pr_review_bot``)
        system = f"{system}\n{SUGGESTION_RULE}"
    if config.get("walkthrough") is True:
        system = f"{system}\n{WALKTHROUGH_RULE}"
    if config.get("acceptance") is True:  # the PR review bot's acceptance table
        system = f"{system}\n{ACCEPTANCE_RULE}"
    if config.get("root_cause") is True:
        system = f"{system}\n{ROOT_CAUSE_RULE}"
    if review.answers:
        system = f"{system}\n{PO_ANSWERS_RULE}" + (f"\n{SPEC_DECISIONS_RULE}" if spec else "")
    if review.tasks:
        from ..task_list import REVIEW_RULE as TASK_LIST_RULE

        system = f"{system}\n{TASK_LIST_RULE}"
    return system


async def _with_spec_decisions(db: AsyncSession, run: WorkflowRun, review: Any, system: str
                               ) -> tuple[Any, str, Any]:
    """The spec's decisions against the code, checked by the platform first: ``(review, system, decisions)``."""
    from ....models import Project
    from ...engineering_knowledge.stacks import for_project
    from .decisions_gate import DECISIONS_TABLE_RULE
    from .spec_commit import recorded_for, technology_catalog
    from .spec_decisions import feature_decisions

    keys, recorded = await recorded_for(db, run)
    stacks = await for_project(db, await db.get(Project, run.project_id) if run.project_id else None)
    decisions = await feature_decisions(await _working_copy(db, run), review.changed, keys,
                                        str(dict(run.context or {}).get("base_sha") or ""), recorded=recorded,
                                        catalog=await technology_catalog(db, run), stacks=stacks)
    if decisions is not None:
        import dataclasses

        from ...content_security.untrusted_fence import fenced_untrusted as fenced

        table = fenced(f"spec decisions ({decisions.spec})", decisions.table(), review.fence)
        review = dataclasses.replace(review, task=f"{review.task}\n\n{table}",
                                     frame=f"{review.frame}\n\n{table}" if review.frame else "")
        system = f"{system}\n{DECISIONS_TABLE_RULE}"
    return review, system, decisions


async def _with_pipeline_needs(db: AsyncSession, run: WorkflowRun, review: Any, system: str, *, spec: bool
                               ) -> tuple[Any, str]:
    """The environment the pipeline's commands need, shown to the reviewer as not in scope."""
    from .pipeline_needs import PIPELINE_NEEDS_RULE, declared

    needs = declared(run, await _working_copy(db, run))
    if needs and not spec:  # finding 27: the environment the pipeline's commands need is not scope
        import dataclasses

        from ...content_security.untrusted_fence import fenced_untrusted

        part = fenced_untrusted("the pipeline's environment", needs, review.fence)
        review = dataclasses.replace(review, task=f"{review.task}\n\n{part}",
                                     frame=f"{review.frame}\n\n{part}" if review.frame else "")
        system = f"{system}\n{PIPELINE_NEEDS_RULE}"
    return review, system


async def _ask_model(db: AsyncSession, run: WorkflowRun, model_factory: ModelFactory, setup: Any, choice: Any,
                     review: Any, config: dict[str, Any], system: str, *, previous: Any, spec: bool
                     ) -> tuple[Any, Any, Any, list[Any]]:
    """Ask the reviewer model and settle its answer: ``(model, answered, settled or None, screenshot notes)``."""
    model = await _review_model(model_factory, db, run, setup, choice)
    root = await _working_copy(db, run)
    screens = _screens(run, config, review, root)
    if screens:
        system = f"{system}\n{SCREENS_RULE}"
    system = f"{system}\n{FOLLOW_UP_RULE if previous else ANSWER_CONTRACT}"
    if previous and config.get("acceptance") is True:
        # The PR review bot's incremental pass re-assesses the listed criteria in the follow-up answer too.
        system = f"{system}\n{ACCEPTANCE_FOLLOW_UP}"
    task, read = review.task, None
    if spec and not previous:
        answered = await _two_stage_spec_review(model, setup, review, system)
    else:
        # A change too large for one call below the price tier is read in parts first (``read_in_parts``).
        task, read = await read_in_parts(model, system.replace(f"\n{SCREENS_RULE}", ""), review)
        answered = await _answer_with_screens(model, system, task, screens, review.screens_task,
                                              follow_up=bool(previous))
        answered = _summed(read, answered) if read is not None else answered
    scope = Scope(review.changed, tuple(screen.name for screen in screens), root)
    notes = list(answered.answer.get(NOTES_KEY) or []) if isinstance(answered.answer, dict) else []
    settled = _settle(answered.answer if previous else look_floor(answered.answer, notes), previous, scope)
    if settled is None:
        # Without a retry, one answer that was no valid verdict paused the run
        # until a person pressed continue. One more ask with the contract restated; a second miss still pauses.
        again = await model.answer(system=f"{system}\n{RETRY_RULE}", user=task)
        settled = _settle(again.answer if previous else look_floor(again.answer, notes), previous, scope)
        answered = _summed(answered, again)
    return model, answered, settled, notes


def _outcome(run: WorkflowRun, config: dict[str, Any], review: Any, setup: Any, choice: Any, model: Any,
             answered: Any, settled: Any, notes: list[Any], *, tests_protected: bool, decisions: Any
             ) -> tuple[Any, Any, str, str, dict[str, Any]]:
    """The review's result from the settled answer, after the platform's own gates, with the reviewer facts."""
    facts = {"reviewer_agent": setup.definition_id,
             "reviewer_runtime_shared": bool(getattr(model, "runtime_shared", False)), **choice.facts(),
             "reviewer_route_used": str(getattr(model, "route", "") or choice.route)}
    if dict(run.context or {}).get("review_left_out") is not None:  # audit: what the shown diff left out
        facts["left_out"] = list(dict(run.context or {}).get("review_left_out") or [])
    if settled is None:
        return None, answered.usage, "invalid_verdict", review.tree, facts
    if config.get("root_cause") is True:
        settled = root_cause_gate(settled)
    if tests_protected:
        from .tests_gate import tests_gate

        settled = tests_gate(settled)
    if decisions is not None:
        from .decisions_gate import decisions_gate

        settled = decisions_gate(settled, decisions)
        facts["spec_decisions"] = decisions.to_dict()
    record = settled.record()
    facts["_diff_lines"] = sum(1 for line in review.diff.splitlines()
                               if line[:1] in "+-" and not line.startswith(("+++", "---")))
    if notes:
        record[NOTES_KEY] = notes  # what the screenshot calls saw, kept to judge the review afterwards
    return settled.verdict, answered.usage, "", review.tree, {**facts, "_record": record}
