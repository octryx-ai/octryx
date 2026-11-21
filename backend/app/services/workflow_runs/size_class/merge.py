"""A size class lays one phase into a later one: ``"merge": {"<phase>": "<later phase>"}``.

after, and: a small bug spent a whole turn on its reproduction and then
went back and forth when an existing test asserted the bug, because the fix phase may change no test. With
``"merge": {"reproduce": "fix"}`` the run never enters the first phase: it is skipped (``node_skipped`` with
``merged_into``), and so is every step on the way to the second one. A platform action's skip duty
(``platform_actions.action_skipped``) waits until the merged phase submits the first one's output. A gate on the
way is not judged: the class's ``red_on_base`` proves the reproduction on the base commit in the pipeline instead.
The run's graph gives the second phase both definitions (:func:`merged_graph`): both texts in order, and the tools,
output, checks and paths of both, so the agent writes the failing test and the fix in one turn. The schema allows
this only between two phases whose way holds nothing but platform actions and gates, and only with ``red_on_base``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event
from . import CONTEXT_KEY as CLASS_CONTEXT
from . import class_config, size_of
from .steps import EVENT_SKIPPED

KEY = "merge"
CONTEXT = "size_merge"


def merges(run: WorkflowRun | None) -> dict[str, str]:
    value = class_config(run).get(KEY)
    return {str(source): str(target) for source, target in value.items()} if isinstance(value, dict) else {}


def _union(first: list[Any] | None, second: list[Any] | None) -> list[Any]:
    out: list[Any] = []
    for item in [*(first or []), *(second or [])]:
        if item not in out:
            out.append(item)
    return out


def merged_config(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """The second phase's config with the first one's work in front of it."""
    config, earlier = dict(second), dict(first)
    policy, before = dict(config.get("tool_policy") or {}), dict(earlier.get("tool_policy") or {})
    allow = _union(before.get("allowlist"), policy.get("allowlist"))
    config["tool_policy"] = {**policy, "allowlist": allow,
                             "denylist": [tool for tool in policy.get("denylist") or [] if tool not in allow]}
    if earlier.get("output") and not config.get("output"):
        config["output"] = earlier["output"]
    config["inputs"] = [item for item in config.get("inputs") or [] if item != earlier.get("output")]
    contract, first_contract = dict(config.get("workflow_contract") or {}), dict(earlier.get("workflow_contract") or {})
    texts = [str(first_contract.get("when_to_use") or "").strip(), str(contract.get("when_to_use") or "").strip()]
    contract["when_to_use"] = " Then, in the same turn: ".join(text for text in texts if text)
    contract["checks"] = _union(first_contract.get("checks"), contract.get("checks"))
    contract["path_rules"] = merged_paths(dict(first_contract.get("path_rules") or {}),
                                          dict(contract.get("path_rules") or {}))
    config["workflow_contract"] = contract
    for key in ("refusals", "builtin_tools"):
        if earlier.get(key) or config.get(key):
            config[key] = _union(earlier.get(key), config.get(key))
    return config


def merged_paths(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """What either phase may change, the merged one may (otherwise the fix
    phase's ``protect_confirmed_tests`` refused every test file, so the reproduction of a merged turn could never
    be written). A phase that names no write paths writes anywhere, so the union does too. The second phase's
    protection of the confirmed tests stays, but only for the tests the platform confirmed (``write_tests``): the
    agent writes its failing test freely and cannot weaken it once it is confirmed, also in the same turn."""
    from ..path_rules import PROTECT_CONFIRMED_TESTS, WRITE_TESTS

    paths = dict(second)
    if first.get("write") and second.get("write"):
        paths["write"] = _union(first["write"], second["write"])
    else:
        paths.pop("write", None)
    if first.get("create") or second.get("create"):
        paths["create"] = _union(first.get("create"), second.get("create"))
    protects = [rules.get(PROTECT_CONFIRMED_TESTS) is True for rules in (first, second)]
    if any(protects):
        paths[PROTECT_CONFIRMED_TESTS] = True
        if not all(protects) or first.get(WRITE_TESTS) is True:
            paths[WRITE_TESTS] = True  # the phase without the protection wrote tests
    return paths


def merged_graph(graph: Any, run: WorkflowRun) -> Any:
    """``graph`` with each merged phase holding both definitions (the run's class decides)."""
    from ..graph import NODE_PHASE, PhasedNode

    for source, target in merges(run).items():
        first, second = graph.nodes.get(source), graph.nodes.get(target)
        if first is not None and second is not None and first.kind == second.kind == NODE_PHASE:
            graph.nodes[target] = PhasedNode(id=second.id, kind=second.kind, title=second.title,
                                             config=merged_config(first.config, second.config))
    return graph


def landing(run: WorkflowRun, graph: Any, node_id: str) -> str:
    """The node a run sent back to ``node_id`` works in: a phase its class merges into a later one is that one, a
    step its class skips is the one its success leads to (a refusal's ``change_plan`` names the workflow's node)."""
    from ..graph import PASSED, SUCCEEDED

    skips = set(dict(dict(run.context or {}).get(CLASS_CONTEXT) or {}).get("skips") or [])
    current, seen = node_id, set()
    while current not in seen:
        seen.add(current)
        if current in merges(run):
            current = merges(run)[current]
        elif current in skips and (edge := next((edge for edge in graph.exits(current)
                                                 if edge.when in (SUCCEEDED, PASSED)), None)) is not None:
            current = edge.target
        else:
            break
    return current


async def entered(db: AsyncSession, run: WorkflowRun, node: Any) -> tuple[bool, Any]:
    """``(True, route)`` when the merge decides the node just entered; ``(False, None)`` for its usual work."""
    from ..graph import NODE_GATE, NODE_PHASE, NODE_PLATFORM_ACTION, PASSED, SUCCEEDED

    context = dict(run.context or {})
    state = dict(context.get(CONTEXT) or {})
    target = merges(run).get(node.id)
    if node.kind == NODE_PHASE and target:
        run.context = {**context, CONTEXT: {"from": node.id, "to": target, "deferred": []}}
        record_event(db, run, EVENT_SKIPPED, node_id=node.id, detail={
            "class": size_of(run), "merged_into": target, "reason": f"class {size_of(run)} does it in '{target}'"})
        return True, None
    if not state or state.get("inside"):
        if state and node.id != state.get("to"):
            run.context = {key: value for key, value in context.items() if key != CONTEXT}  # the merge is over
        return False, None
    if node.id == state.get("to"):
        run.context = {**context, CONTEXT: {**state, "inside": True}}
        return False, None
    if node.kind not in (NODE_PLATFORM_ACTION, NODE_GATE):
        return False, None  # the schema allows nothing else on the way
    if node.kind == NODE_PLATFORM_ACTION:
        state["deferred"] = [*state.get("deferred", []), node.id]
        run.context = {**context, CONTEXT: state}
    record_event(db, run, EVENT_SKIPPED, node_id=node.id, detail={
        "class": size_of(run), "merged_into": state.get("to"),
        "reason": f"'{state.get('from')}' is done inside '{state.get('to')}'"})
    return True, SUCCEEDED if node.kind == NODE_PLATFORM_ACTION else PASSED


async def output_recorded(db: AsyncSession, run: WorkflowRun, graph: Any, node: Any) -> None:
    """The merged phase submitted the first one's output: the skipped actions on the way now do their duty, and the
    submitted reproduction becomes the confirmed tests (:func:`confirm_in_turn`)."""
    from ..platform_actions import action_skipped

    context = dict(run.context or {})
    state = dict(context.get(CONTEXT) or {})
    if node.id not in merges(run).values():
        return
    if state.get("deferred") and node.id == state.get("to"):
        run.context = {**context, CONTEXT: {**state, "deferred": []}}
        for node_id in state["deferred"]:
            if node_id in graph.nodes:
                await action_skipped(db, run, graph.nodes[node_id])
    await confirm_in_turn(db, run)


async def confirm_in_turn(db: AsyncSession, run: WorkflowRun) -> None:
    """The merged phase's reproduction is confirmed when it is submitted, from the tests it names.

    Without this, the skipped reproduce check confirmed only
    tests the newest recorded run showed failing, but a merged turn's runs are recorded when the turn ends, after the
    submission; nothing was confirmed and the ``green`` gate failed on "no confirmed tests" at every turn's end until
    the class escalated. Here the submitted tests are bound (a newer submission in the same merge rebinds), and their
    red is the class's ``red_on_base``: the pipeline after the phase runs them on the base commit and stays red unless
    each fails there, so ``tests_green`` need not have seen them fail inside the turn (``RED_ON_BASE_PENDING``)."""
    from ..confirmation_payloads import reproduction_roles
    from ..phase_outputs import recorded_output
    from ..test_runs import RED_ON_BASE_PENDING, confirm_tests, confirmed_tests, snapshot_confirmed_tests

    if not class_config(run).get("red_on_base"):
        return
    tests_state = dict(dict(run.context or {}).get("tests") or {})
    if confirmed_tests(run) and not tests_state.get(RED_ON_BASE_PENDING):
        return  # the skipped check bound them from a red run: that is the stronger evidence
    from ..workspace.run_app import APP_KEY

    record = dict(dict(recorded_output(run, "reproduction") or {}).get("record") or {})
    # Named from the app folder, as its test runs and the base run name them (the agent may name them from the root).
    app = str(dict(dict(run.context or {}).get(APP_KEY) or {}).get("path") or "").strip("/")
    prefix = f"{app}/" if app and app != "." else ""
    tests = [test[len(prefix):] if prefix and test.startswith(prefix) else test
             for test in (str(item).strip() for item in record.get("tests") or []) if test]
    if not tests:
        return
    confirm_tests(run, tests, symptom=str(record.get("symptom") or "") or None, roles=reproduction_roles(tests),
                  by="run")
    context = dict(run.context or {})
    context["tests"] = {**dict(context.get("tests") or {}), RED_ON_BASE_PENDING: True}
    run.context = context
    await snapshot_confirmed_tests(db, run)


__all__ = ["CONTEXT", "KEY", "confirm_in_turn", "entered", "landing", "merged_config", "merged_graph", "merged_paths",
           "merges", "output_recorded"]
