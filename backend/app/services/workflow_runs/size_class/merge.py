"""A size class lays one phase into a later one: ``"merge": {"<phase>": "<later phase>"}``."""

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
    # Only the confirmed tests stay protected: the agent writes its failing test freely but cannot weaken it later.
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
            paths[WRITE_TESTS] = True
    return paths


def merged_graph(graph: Any, run: WorkflowRun) -> Any:
    from ..graph import NODE_PHASE, PhasedNode

    for source, target in merges(run).items():
        first, second = graph.nodes.get(source), graph.nodes.get(target)
        if first is not None and second is not None and first.kind == second.kind == NODE_PHASE:
            graph.nodes[target] = PhasedNode(id=second.id, kind=second.kind, title=second.title,
                                             config=merged_config(first.config, second.config))
    return graph


def landing(run: WorkflowRun, graph: Any, node_id: str) -> str:
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
            run.context = {key: value for key, value in context.items() if key != CONTEXT}
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
    # A merged turn's test runs are recorded only after the submission, so the submitted tests are bound here.
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
