"""Cedar → builder model: the read-back half of ``builder``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..data_classification.levels import level_registry
from . import catalog
from .builder import ENTITY_OF_MODE, render
from .builder_content import ANNOTATIONS as CONTENT_ANNOTATIONS
from .builder_content_parse import content_of, read_content_unless, read_content_when
from .builder_est import Found
from .builder_est import RefusedError as _RefusedError
from .builder_est import chain as _chain
from .builder_est import entities as _entities
from .builder_est import op as _op
from .builder_est import path as _path
from .builder_est import strings as _strings
from .builder_est import value as _value
from .builder_model import BUILDER_VERSION, Conditions, PolicyModel, What, Where, Who
from .engine import cedar_module

MODE_OF_ENTITY = {value: key for key, value in ENTITY_OF_MODE.items()}


def _level_at(rank: Any, allowed: tuple[str, ...]) -> str:
    level = level_registry().at_rank(rank)
    if level is None or level.key not in allowed:
        raise _RefusedError
    return level.key


def _like(node: Any) -> str:
    operator, body = _op(node)
    if operator != "like" or _path(body["left"]) != ("resource", "path"):
        raise _RefusedError
    return "".join("*" if part == "Wildcard" else str(part.get("Literal", "")) for part in body["pattern"])


def _principal_in(node: Any) -> tuple[str, str]:
    operator, body = _op(node)
    if operator != "in" or _path(body["left"]) != ("principal",):
        raise _RefusedError
    ref = _value(body["right"]).get("__entity", {})
    if ref.get("type") not in MODE_OF_ENTITY:
        raise _RefusedError
    return MODE_OF_ENTITY[ref["type"]], str(ref["id"])


def _read_when(items: list[Any], found: Found) -> None:
    index = 0
    while index < len(items):
        node = items[index]
        nxt = items[index + 1] if index + 1 < len(items) else None
        if read_content_when(node, found):
            index += 1
            continue
        operator, body = _op(node)
        if operator == "is" and _path(body["left"]) == ("principal",) and body.get("entity_type") == "AgentSession":
            attr_op, attr = _op(nxt)
            if attr_op != "==" or _path(attr["left"])[:1] != ("principal",):
                raise _RefusedError
            name = _path(attr["left"])[1:]
            if name not in (("profile",), ("client",)):
                raise _RefusedError
            found.put(f"session_{name[0]}", _value(attr["right"]))
            index += 2
            continue
        if operator == "has":
            target, attr_name = _path(body["left"]), body.get("attr")
            follow_op, follow = _op(nxt)
            if target == ("context", "workspace") and attr_name == "classification" and follow_op == "contains" \
                    and _path(follow["right"]) == ("context", "workspace", "classification"):
                found.put("classification_is", _strings(follow["left"]))
            elif target == ("context", "workspace") and attr_name == "classification_rank" and follow_op == ">=" \
                    and _path(follow["left"]) == ("context", "workspace", "classification_rank"):
                found.put("classification_at_least",
                          _level_at(_value(follow["right"]), catalog.classification_levels()))
            elif target == ("resource",) and attr_name == "data_policy_rank" and follow_op == "<" \
                    and _path(follow["left"]) == ("resource", "data_policy_rank"):
                found.put("remote_class_below", _level_at(_value(follow["right"]), catalog.data_policy_classes()))
            else:
                raise _RefusedError
            index += 2
            continue
        _read_single(operator, body, node, found)
        index += 1


def _read_single(operator: str, body: Any, node: Any, found: Found) -> None:
    if operator == "||":
        parts = _chain(node, "||")
        if all(_op(part)[0] == "like" for part in parts):
            found.put("paths", tuple(_like(part) for part in parts))
            return
        pairs = [_principal_in(part) for part in parts]
        if len({mode for mode, _ in pairs}) != 1:
            raise _RefusedError
        found.put("who", (pairs[0][0], tuple(item for _, item in pairs)))
        return
    if operator == "like":
        found.put("paths", (_like(node),))
        return
    if operator == "!":
        inner_op, inner = _op(body["arg"])
        if inner_op == "has" and _path(inner["left"]) == ("context", "workspace") and inner["attr"] == "classification":
            found.put("unclassified", True)
        elif _path(body["arg"]) == ("resource", "parseable"):
            found.put("unparseable", True)
        elif _path(body["arg"]) == ("context", "admission_verified"):
            found.put("admission_unverified", True)
        else:
            raise _RefusedError
        return
    _read_fact(operator, body, node, found)


def _read_fact(operator: str, body: Any, node: Any, found: Found) -> None:
    if operator == "in":
        left = _path(body["left"])
        if left == ("context", "workspace"):
            found.put("workspaces", _entities(body["right"], "Workspace"))
        elif left == ("resource",) and body["right"].get("Set") and \
                body["right"]["Set"][0].get("Value", {}).get("__entity", {}).get("type") == "ConnectorFamily":
            found.put("families", _entities(body["right"], "ConnectorFamily"))
        elif left == ("resource",):
            found.put("tools", _entities(body["right"], "Tool"))
        else:
            raise _RefusedError
        return
    if operator in ("containsAny", "containsAll"):
        key = {("context", "connections", "containsAny"): "connections",
               ("resource", "prefixes", "containsAny"): "prefixes",
               ("resource", "arguments", "containsAll"): "arguments",
               ("resource", "argument_values", "containsAny"): "option_values"}.get((*_path(body["left"]), operator))
        if key is None:
            raise _RefusedError
        found.put(key, _strings(body["right"]))
        return
    if operator == "contains":
        key = {("resource", "alias"): "models_only", ("resource", "program"): "programs",
               ("context", "tool"): "client_tools"}.get(_path(body["right"]))
        if key is None:
            raise _RefusedError
        found.put(key, _strings(body["left"]))
        return
    if operator == "==" and _path(body["left"]) == ("resource", "seat_mode"):
        found.put("seat_mode", _value(body["right"]))
        return
    flag = {("context", "writes"): "writes_only", ("context", "reads_logs"): "reads_logs",
            ("resource", "requires_governed_routing"): "governed_required"}.get(_path(node))
    if flag is None:
        raise _RefusedError
    found.put(flag, True)


def _read_unless(items: list[Any], found: Found) -> None:
    for node in items:
        if read_content_unless(node, found):
            continue
        operator, body = _op(node)
        if operator == "contains" and _path(body["right"]) == ("resource", "alias"):
            found.put("models_except", _strings(body["left"]))
        elif operator == "containsAny" and _path(body["left"]) == ("resource", "argument_values"):
            found.put("unless_option_values", _strings(body["right"]))
        elif operator == "&&":
            left_op, left = _op(body["left"])
            if left_op != "is" or left.get("entity_type") != "User" or _path(left["left"]) != ("principal",) \
                    or _path(body["right"]) != ("principal", "platform_admin"):
                raise _RefusedError
            found.put("except_admins", True)
        else:
            raise _RefusedError


def _model_of(est: Mapping[str, Any]) -> PolicyModel:
    annotations = {str(key): str(value) for key, value in (est.get("annotations") or {}).items()}
    if annotations.get("builder") != BUILDER_VERSION or set(annotations) - {
            "id", "name", "description", "template", "builder", *CONTENT_ANNOTATIONS}:
        raise _RefusedError
    if est.get("effect") != "forbid" or (est.get("resource") or {}).get("op") != "All":
        raise _RefusedError
    scope = est.get("action") or {}
    listed = scope.get("entities") or ()
    actions = (scope["entity"]["id"],) if scope.get("op") == "==" else tuple(item["id"] for item in listed)
    if not actions:
        raise _RefusedError
    found = Found()
    principal = est.get("principal") or {}
    if principal.get("op") == "in" and principal.get("entity", {}).get("type") in MODE_OF_ENTITY:
        found.put("who", (MODE_OF_ENTITY[principal["entity"]["type"]], (str(principal["entity"]["id"]),)))
    elif principal.get("op") != "All":
        raise _RefusedError
    kinds = [item.get("kind") for item in est.get("conditions") or ()]
    if kinds not in ([], ["when"], ["unless"], ["when", "unless"]):
        raise _RefusedError
    for clause in est.get("conditions") or ():
        if clause["kind"] == "when":
            _read_when(_chain(clause["body"], "&&"), found)
        else:
            _read_unless(_chain(clause["body"], "||"), found)
    values = found.values
    if "models_only" in values and "models_except" in values:
        raise _RefusedError
    mode, items = values.get("who", ("everyone", ()))
    models = values.get("models_only") or values.get("models_except") or ()
    content, outcome = content_of(values, annotations)
    return PolicyModel(
        id=annotations.get("id", ""), name=annotations.get("name", ""), description=annotations.get("description", ""),
        template=annotations.get("template", ""), actions=tuple(str(item) for item in actions),
        who=Who(mode=mode, items=items, except_admins=values.get("except_admins", False),
                session_profile=values.get("session_profile", ""), session_client=values.get("session_client", "")),
        what=What(families=values.get("families", ()), tools=values.get("tools", ()),
                  writes_only=values.get("writes_only", False), reads_logs=values.get("reads_logs", False),
                  models=models, model_mode="only" if "models_only" in values else "except",
                  remote_class_below=values.get("remote_class_below", ""), programs=values.get("programs", ()),
                  prefixes=values.get("prefixes", ()), arguments=values.get("arguments", ()),
                  option_values=values.get("option_values", ()), unparseable=values.get("unparseable", False),
                  paths=values.get("paths", ()), client_tools=values.get("client_tools", ())),
        where=Where(workspaces=values.get("workspaces", ()),
                    classification_at_least=values.get("classification_at_least", ""),
                    classification_is=values.get("classification_is", ()),
                    unclassified=values.get("unclassified", False), connections=values.get("connections", ())),
        conditions=Conditions(unless_option_values=values.get("unless_option_values", ()),
                              admission_unverified=values.get("admission_unverified", False),
                              seat_mode=values.get("seat_mode", ""),
                              governed_required=values.get("governed_required", False),
                              route=values.get("route", "")),
        content=content, outcome=outcome,
    )


def parse_est(est: Mapping[str, Any], text: str) -> PolicyModel | None:
    from .builder_model import model_from_json

    try:
        candidate = _model_of(est)
    except (_RefusedError, KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    model, issues = model_from_json(candidate.to_json())
    if model is None or issues or render(model) != text.strip():
        return None
    return model


def parse(text: str) -> PolicyModel | None:
    try:
        est = json.loads(cedar_module().policies_to_json_str(text))
    except ValueError:
        return None
    bodies = list((est.get("staticPolicies") or {}).values())
    return parse_est(bodies[0], text) if len(bodies) == 1 and not est.get("templates") else None



__all__ = ["parse", "parse_est"]
