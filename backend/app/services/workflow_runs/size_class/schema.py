"""Validation of a workflow definition's ``size_classes`` block (refused with a code and a clear text).

The block (all of it the workflow owner's data, editable like the rest of the definition)::

    "size_classes": {
      "default": "<class>",
      "rules": [{"class": "<class>", "when": {"issue_type_in": [...], "labels_any": [...], ...}}],
      "classes": {"<class>": {"session": "shared" | "per_phase", "context_cap_tokens": <int>,
                              "phase_change": "same_turn" | "new_turn", "red_on_base": true | false,
                              "merge": {"<phase>": "<later phase>"}, "builtin_tools": ["<tool>", ...],
                              "agent_tests": "affected" | "full",
                              "pipeline_scope": {"system_test": "always" | "labels", "system_test_labels": [...]},
                              "skip_nodes": [{"node": "<node id>", "unless_labels": [...]}],
                              "max_rounds": <int> | {"<loop edge id>" | "*": <int>},
                              "escalate_to": "<class>", "agent_note": "<text>"}}}

A skipped node must be a platform action the catalog marks skippable (a check whose result no later step needs as
evidence, never a push, a pull request or a report) and must have a ``succeeded`` exit, which the run then takes.
``phase_change: same_turn`` carries a passed phase into the next one inside the running turn and needs the shared
session (``octryx/same_turn``). ``red_on_base`` runs the confirmed tests on the base commit in the pipeline; each
must fail there (``workflow_runs/red_on_base``). ``merge`` does a phase inside a later one (``size_class/merge``):
only between two phases whose way holds nothing but platform actions and gates, and only with ``red_on_base``.
"""

from __future__ import annotations

import re
from typing import Any

from .rules import CONDITIONS

_COUNTS = ("criteria_min", "criteria_max", "labels_count_max", "components_count_max")

CLASS_KEYS = frozenset({"session", "context_cap_tokens", "skip_nodes", "max_rounds", "escalate_to", "agent_note",
                        "phase_change", "red_on_base", "merge", "builtin_tools", "agent_tests", "stall_after",
                        "pipeline_scope"})
SESSIONS = frozenset({"shared", "per_phase"})
PHASE_CHANGES = frozenset({"same_turn", "new_turn"})


def _error(message: str) -> dict[str, str]:
    return {"code": "size_classes_invalid", "message": f"size_classes: {message}"}


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _rule_errors(rules: Any, names: set[str]) -> list[dict[str, str]]:
    if not isinstance(rules, list):
        return [_error("rules is a list of {class, when}.")]
    errors = []
    for number, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict) or str(rule.get("class") or "") not in names:
            errors.append(_error(f"rule {number} names a class that is not in classes."))
            continue
        when = rule.get("when") or {}
        if not isinstance(when, dict) or set(when) - CONDITIONS:
            errors.append(_error(f"rule {number}: when takes {', '.join(sorted(CONDITIONS))}."))
            continue
        for name in ("text_matches", "text_not_matches"):
            try:
                re.compile(str(when[name])) if name in when else None
            except re.error:
                errors.append(_error(f"rule {number}: {name} is not a valid pattern."))
        if any(name in when and type(when[name]) is not int for name in _COUNTS):
            errors.append(_error(f"rule {number}: {', '.join(_COUNTS)} are whole numbers."))
    return errors


def _skip_errors(name: str, skips: Any, graph: Any) -> list[dict[str, str]]:
    from ..graph import NODE_PLATFORM_ACTION, SUCCEEDED
    from ..platform.catalog import ACTIONS

    if not isinstance(skips, list):
        return [_error(f"class {name}: skip_nodes is a list of {{node, unless_labels}}.")]
    errors = []
    for skip in skips:
        node = graph.nodes.get(str(dict(skip or {}).get("node") or "")) if isinstance(skip, dict) else None
        if node is None:
            errors.append(_error(f"class {name}: skip_nodes names a node this workflow does not have."))
            continue
        spec = ACTIONS.get(str(node.config.get("action") or "")) if node.kind == NODE_PLATFORM_ACTION else None
        if spec is None or not spec.skippable:
            errors.append(_error(f"class {name}: '{node.id}' cannot be skipped; only a check step whose result no "
                                 "later step needs as evidence can (never a push, a pull request or a report)."))
        elif "unless_changed" in skip and skip["unless_changed"] != "ui_paths":
            errors.append(_error(f"class {name}: skip_nodes unless_changed is \"ui_paths\" (the stacks' data)."))
        elif not any(edge.when == SUCCEEDED for edge in graph.exits(node.id)):
            errors.append(_error(f"class {name}: '{node.id}' has no 'succeeded' exit for a skipped pass to take."))
    return errors


def _rounds_errors(name: str, rounds: Any, graph: Any) -> list[dict[str, str]]:
    if _positive(rounds):
        return []
    loops = {edge.id for edge in graph.loop_edges()}
    if not isinstance(rounds, dict) or not all(_positive(value) for value in rounds.values()) or (
            set(rounds) - loops - {"*"}):
        return [_error(f"class {name}: max_rounds is a positive number or {{loop edge id or '*': number}}.")]
    return []


def _class_errors(name: str, settings: Any, names: set[str], graph: Any) -> list[dict[str, str]]:
    if not isinstance(settings, dict) or set(settings) - CLASS_KEYS:
        return [_error(f"class {name} takes {', '.join(sorted(CLASS_KEYS))}.")]
    errors = []
    if "session" in settings and settings["session"] not in SESSIONS:
        errors.append(_error(f"class {name}: session is shared or per_phase."))
    if "phase_change" in settings and (settings["phase_change"] not in PHASE_CHANGES or (
            settings["phase_change"] == "same_turn" and settings.get("session", "shared") != "shared")):
        errors.append(_error(f"class {name}: phase_change is same_turn (with session shared) or new_turn."))
    tools = settings.get("builtin_tools")
    if "builtin_tools" in settings and not (isinstance(tools, list) and tools and all(
            isinstance(name, str) and name.strip() for name in tools)):
        errors.append(_error(f"class {name}: builtin_tools names the coding engine's built-in tools a turn gets."))
    if "red_on_base" in settings and not isinstance(settings["red_on_base"], bool):
        errors.append(_error(f"class {name}: red_on_base is true or false."))
    stall = settings.get("stall_after")
    if "stall_after" in settings and not (isinstance(stall, int) and not isinstance(stall, bool) and stall >= 1):
        errors.append(_error(f"class {name}: stall_after is the identical stop that pauses (1 or more)."))
    if "context_cap_tokens" in settings and not _positive(settings["context_cap_tokens"]):
        errors.append(_error(f"class {name}: context_cap_tokens is a positive number."))
    if "escalate_to" in settings and (settings["escalate_to"] not in names or settings["escalate_to"] == name):
        errors.append(_error(f"class {name}: escalate_to names another class."))
    if "max_rounds" in settings:
        errors.extend(_rounds_errors(name, settings["max_rounds"], graph))
    if "skip_nodes" in settings:
        errors.extend(_skip_errors(name, settings["skip_nodes"], graph))
    if "merge" in settings:
        errors.extend(_merge_errors(name, settings, graph))
    if "agent_tests" in settings:
        errors.extend(_agent_tests_errors(name, settings["agent_tests"], graph))
    if "pipeline_scope" in settings:
        from .pipeline_scope import errors as scope_errors

        errors.extend(_error(message) for message in scope_errors(name, settings["pipeline_scope"]))
    return errors


def _agent_tests_errors(name: str, value: Any, graph: Any) -> list[dict[str, str]]:
    """``affected`` leaves the whole suite to a pipeline after each phase that changes code; without one nobody would
    run it."""
    if value not in ("affected", "full"):
        return [_error(f"class {name}: agent_tests is affected or full.")]
    if value == "full":
        return []
    from ..graph import NODE_PHASE
    from ..octryx.declared_suite import CHANGING
    from ..octryx.system_tests import tests_only
    from .tests_scope import pipeline_later

    lonely = [node.id for node in graph.nodes.values() if node.kind == NODE_PHASE
              and str(dict(node.config.get("workflow_contract") or {}).get("capability_class") or "") in CHANGING
              and not tests_only(list(dict(dict(node.config.get("workflow_contract") or {}).get("path_rules") or {})
                                      .get("write") or []))
              and not pipeline_later(graph, node.id)]
    return [_error(f"class {name}: agent_tests affected needs a pipeline after {', '.join(lonely)}, which runs the "
                   "whole suite.")] if lonely else []


MERGE_STEPS = 12  # a guard: the way between two merged phases is short


def _way(graph: Any, source: str, target: str) -> bool:
    """Whether ``source``'s plain exit reaches ``target`` over platform actions (succeeded) and gates (passed)."""
    from ..graph import NODE_GATE, NODE_PLATFORM_ACTION, PASSED, SUCCEEDED

    route = {None: None, NODE_PLATFORM_ACTION: SUCCEEDED, NODE_GATE: PASSED}
    current, kind = source, None
    for _ in range(MERGE_STEPS):
        edge = next((edge for edge in graph.exits(current) if edge.when == route[kind]), None)
        node = graph.nodes.get(edge.target) if edge is not None else None
        if node is None:
            return False
        if node.id == target:
            return True
        if node.kind not in (NODE_PLATFORM_ACTION, NODE_GATE):
            return False
        current, kind = node.id, node.kind
    return False


def _merge_errors(name: str, settings: dict[str, Any], graph: Any) -> list[dict[str, str]]:
    from ..graph import NODE_PHASE

    merge = settings["merge"]
    if not isinstance(merge, dict) or not merge:
        return [_error(f"class {name}: merge maps a phase to a later phase.")]
    errors = [] if settings.get("red_on_base") is True else [
        _error(f"class {name}: merge needs red_on_base: the base commit proves what the merged phase reproduced.")]
    for source, target in merge.items():
        nodes = [graph.nodes.get(str(source)), graph.nodes.get(str(target))]
        if any(node is None or node.kind != NODE_PHASE for node in nodes) or not _way(graph, str(source), str(target)):
            errors.append(_error(f"class {name}: merge {source} into {target} needs two phases whose way holds only "
                                 "platform actions and gates."))
    return errors


def _cycle(classes: dict[str, Any]) -> bool:
    for start in classes:
        seen, current = {start}, classes[start].get("escalate_to")
        while current:
            if current in seen:
                return True
            seen.add(current)
            current = dict(classes.get(current) or {}).get("escalate_to")
    return False


def size_class_errors(block: Any, graph: Any) -> list[dict[str, str]]:
    """The block's validation errors (``[]`` without a block: the workflow runs as it always did)."""
    if block is None:
        return []
    if not isinstance(block, dict) or set(block) - {"default", "rules", "classes"}:
        return [_error("the block takes default, rules and classes.")]
    classes = block.get("classes")
    if not isinstance(classes, dict) or not classes:
        return [_error("classes names at least one class.")]
    names = set(classes)
    errors = [] if block.get("default") in names else [_error("default names one of the classes.")]
    errors.extend(_rule_errors(block.get("rules") or [], names))
    for name, settings in classes.items():
        errors.extend(_class_errors(name, settings, names, graph))
    if not errors and _cycle(classes):
        errors.append(_error("escalate_to must not lead back to a class it came from."))
    return errors


__all__ = ["CLASS_KEYS", "PHASE_CHANGES", "SESSIONS", "size_class_errors"]
