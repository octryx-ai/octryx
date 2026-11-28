"""The routes that take a Workspace id, read from the running application, and the smallest request each accepts."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import re
import textwrap
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi.params import File, Form
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.db import Base
from app.main import app

# project_id, workspace_id, target_project_id, source_workspace_id and their list forms.
WORKSPACE_NAME = re.compile(r"^(?:target_|source_|scope_)?(?:project|workspace)_ids?$")
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Every API request is logged (``audit_log`` rows of resource type ``api`` and ``request_audit_logs``), a refused one
# too; any other row, an action's own audit record included, is a write.
REQUEST_LOG_TABLES = frozenset({"request_audit_logs"})
REQUEST_LOG_RESOURCE_TYPE = "api"


@dataclass(frozen=True)
class RouteCase:
    method: str
    path: str
    # (shape, name): shape is path, query, form, model (a body model field) or dict (a key of a plain dict body).
    slots: tuple[tuple[str, str], ...]
    body_model: type | None = None
    body_name: str | None = None
    embed: bool = False
    query: tuple[tuple[str, Any], ...] = ()
    form: tuple[tuple[str, Any], ...] = ()
    files: tuple[str, ...] = ()
    path_types: tuple[tuple[str, Any], ...] = field(default=())
    # The qualified names of the route's dependencies (``workspace_resource_rows.REQUEST_REFERENCES``).
    dependencies: tuple[str, ...] = ()

    @property
    def shapes(self) -> frozenset[str]:
        return frozenset(shape for shape, _name in self.slots)

    @property
    def addresses_a_resource(self) -> bool:
        workspace_paths = {name for shape, name in self.slots if shape == "path"}
        return bool(workspace_paths) or any(name != "user_id" for name, _type in self.path_types)


def _dependants(dependant):
    yield dependant
    for sub in dependant.dependencies:
        yield from _dependants(sub)


def _model_fields(model: Any, prefix: str = "", depth: int = 0) -> list[str]:
    fields = getattr(model, "model_fields", None) or {}
    found = []
    for name, info in fields.items():
        if WORKSPACE_NAME.match(name):
            found.append(prefix + name)
        nested = info.annotation
        if depth < 2 and isinstance(nested, type) and hasattr(nested, "model_fields") and info.is_required():
            found.extend(_model_fields(nested, f"{prefix}{name}.", depth + 1))
    return found


# A key read from a mapping (``body.get("project_id")``, ``payload["workspace_id"]``) in a function the route calls.
_READ_KEY = re.compile(r"""(?:\.get\(\s*|\[)["'](\w+)["']""")
CALL_DEPTH = 3
# Routes whose called functions read a Workspace key from a mapping that is not the request body; the body itself
# names no Workspace, so its dict slots are dropped (with the reason).
NOT_A_BODY_KEY = {
    ("POST", "/api/v1/workspaces/{workspace_id}/repositories"):
        "the body names a connection; the Workspace is the path's (the keys are read from connection rows)",
    ("POST", "/api/v1/phased-workflows"):
        "the body is title and description; the draft is created without a Workspace from the request",
    ("POST", "/api/v1/admin/policy-engine/tests/run"):
        "the body is the policy source; the Workspaces are the saved cases' (checked when a case is saved)",
    ("POST", "/api/v1/admin/policy-engine/test-bench/generate"):
        "the body is a policy model; the generated questions name no requested Workspace",
}


def _called_functions(function: Any) -> list[Any]:
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    except (OSError, TypeError, SyntaxError):
        return []
    names = dict(getattr(function, "__globals__", {}))
    module = inspect.getmodule(function)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and module is not None:
            try:
                source = importlib.import_module(
                    "." * node.level + (node.module or ""), module.__package__ if node.level else None)
            except ImportError:
                continue
            names.update({alias.asname or alias.name: getattr(source, alias.name, None) for alias in node.names})
    called = []
    for node in ast.walk(tree):
        target = node.func if isinstance(node, ast.Call) else None
        if isinstance(target, ast.Name):
            value = names.get(target.id)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            value = getattr(names.get(target.value.id), target.attr, None)
        else:
            continue
        value = inspect.unwrap(value) if callable(value) else None
        if inspect.isfunction(value) and value.__module__.startswith("app."):
            called.append(value)
    return called


def _dict_keys(route: APIRoute) -> list[str]:
    try:
        source = inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return []
    keys = {key for key in re.findall(r"""["'](\w+)["']""", source) if WORKSPACE_NAME.match(key)}
    seen, frontier = {route.endpoint}, _called_functions(route.endpoint)
    for _depth in range(CALL_DEPTH):
        following = []
        for function in frontier:
            if function in seen:
                continue
            seen.add(function)
            try:
                keys.update(key for key in _READ_KEY.findall(inspect.getsource(function)) if WORKSPACE_NAME.match(key))
            except (OSError, TypeError):
                continue
            following.extend(_called_functions(function))
        frontier = following
    return sorted(keys)


# A Workspace key a dependency reads from the request itself, not through a declared parameter.
_QUERY_READ = re.compile(r"""query_params\.(?:get|getlist)\(\s*["'](\w+)["']""")
_BODY_READ = re.compile(r"""\bbody\.get\(\s*["'](\w+)["']""")


def _request_sources(call: Any) -> list[str]:
    sources, seen, frontier = [], set(), [call]
    for _depth in range(CALL_DEPTH + 1):
        following = []
        for function in frontier:
            if function in seen:
                continue
            seen.add(function)
            try:
                sources.append(inspect.getsource(function))
            except (OSError, TypeError):
                continue
            following.extend(_called_functions(function))
        frontier = following
    return sources


def _request_reads(dependant: Any, method: str) -> list[tuple[str, str]]:
    call = getattr(dependant, "call", None)
    if call is None or dependant.request_param_name is None:
        return []
    found = []
    for source in _request_sources(call):
        found += [("query", key) for key in _QUERY_READ.findall(source) if WORKSPACE_NAME.match(key)]
        if method in WRITE_METHODS:
            found += [("dict", key) for key in _BODY_READ.findall(source) if WORKSPACE_NAME.match(key)]
    return found


def _scalar(annotation: Any) -> Any:
    text = str(annotation)
    if annotation is int or "int" in text and "str" not in text:
        return 1
    if annotation is bool:
        return "false"
    return "x"


def _case(route: APIRoute, method: str) -> RouteCase | None:
    slots: list[tuple[str, str]] = []
    query, form, files = [], [], []
    body_model = body_name = None
    embed = False
    for dependant in _dependants(route.dependant):
        slots.extend(_request_reads(dependant, method))
        for param in dependant.path_params:
            if WORKSPACE_NAME.match(param.name):
                slots.append(("path", param.name))
        for param in dependant.query_params:
            if WORKSPACE_NAME.match(param.name):
                slots.append(("query", param.name))
            elif param.field_info.is_required():
                query.append((param.alias, _scalar(param.field_info.annotation)))
        for param in dependant.body_params:
            info = param.field_info
            if isinstance(info, File):
                files.append(param.alias)
            elif isinstance(info, Form):
                if WORKSPACE_NAME.match(param.name):
                    slots.append(("form", param.alias))
                elif info.is_required():
                    form.append((param.alias, _scalar(info.annotation)))
            elif hasattr(info.annotation, "model_fields"):
                body_model, body_name, embed = info.annotation, param.alias, bool(getattr(info, "embed", False))
                slots.extend(("model", name) for name in _model_fields(info.annotation))
            else:
                body_name = param.alias
                if (method, route.path) not in NOT_A_BODY_KEY:
                    slots.extend(("dict", key) for key in _dict_keys(route))
    if not slots:
        return None
    path_types = tuple((param.name, param.field_info.annotation) for param in route.dependant.path_params)
    dependencies = tuple(dict.fromkeys(f"{call.__module__}.{call.__qualname__}" for dependant in
                                       _dependants(route.dependant) if (call := getattr(dependant, "call", None))
                                       and hasattr(call, "__qualname__")))
    return RouteCase(method, route.path, tuple(dict.fromkeys(slots)), body_model, body_name, embed, tuple(query),
                     tuple(form), tuple(files), path_types, dependencies)


def workspace_routes() -> list[RouteCase]:
    cases = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            case = _case(route, method)
            if case is not None:
                cases.append(case)
    return sorted(cases, key=lambda case: (case.path, case.method))


def refuses_an_unknown_workspace(case: RouteCase) -> bool:
    return case.method in WRITE_METHODS or "model" in case.shapes


def _value(schema: dict[str, Any], defs: dict[str, Any]) -> Any:
    if "$ref" in schema:
        return _value(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [option for option in schema[key] if option.get("type") != "null"]
            return _value(options[0], defs)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    kind = schema.get("type")
    if kind == "string":
        # A constrained id (a hex or uuid pattern) gets a hex id; any other string the shortest it accepts.
        if "pattern" in schema:
            return str(uuid.uuid4()) if int(schema.get("minLength") or 0) > 32 else uuid.uuid4().hex
        return "x" * max(1, int(schema.get("minLength") or 1))
    if kind in ("integer", "number"):
        return max(1, int(schema.get("minimum") or 1))
    if kind == "boolean":
        return False
    if kind == "array":
        return [_value(schema.get("items") or {"type": "string"}, defs)] * int(schema.get("minItems") or 0)
    if kind == "object":
        return _payload(schema, defs)
    return "x"


def _payload(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    return {name: _value(properties[name], defs) for name in schema.get("required") or [] if name in properties}


# Bodies whose model needs one of two fields beyond the required ones (a model validator).
EXTRA_FIELDS = {"ImportPackageRequest": {"package_id": "x"}, "DataImportJobCreateRequest": {"payload_text": "x"}}


def _set(body: dict[str, Any], dotted: str, workspace_id: str) -> None:
    *outer, name = dotted.split(".")
    target = body
    for key in outer:
        target = target.setdefault(key, {})
    target[name] = [workspace_id] if name.endswith("_ids") else workspace_id


def _location(shape: str) -> str:
    return "body" if shape in ("model", "dict") else shape


def request_slots(case: RouteCase) -> list[tuple[str, str]]:
    return list(dict.fromkeys((_location(shape), name) for shape, name in case.slots))


def build_request(case: RouteCase, workspace_id: str, caller_id: str, *, own_workspace_id: str | None = None,
                  varied: tuple[str, str] | None = None, path_values: dict[str, str] | None = None,
                  references: dict[str, str] | None = None) -> dict[str, Any]:
    def named(shape: str, name: str) -> str:
        return workspace_id if varied is None or (_location(shape), name) == varied else own_workspace_id

    names = {name: shape for shape, name in case.slots}
    types = dict(case.path_types)
    url = case.path
    while "{" in url:
        start, end = url.index("{"), url.index("}")
        name = url[start + 1:end]
        # The caller's own id where the path names a user (an API key is created by its owner only).
        value = (named("path", name) if names.get(name) == "path" else caller_id if name == "user_id"
                 else (path_values or {}).get(name) or ("1" if types.get(name) is int else uuid.uuid4().hex))
        url = url[:start] + value + url[end + 1:]
    query = dict(case.query) | {name: named(shape, name) for shape, name in case.slots if shape == "query"}
    if references and case.method not in WRITE_METHODS:
        query |= references
    request: dict[str, Any] = {"url": url, "params": query}
    form = dict(case.form) | {name: named(shape, name) for shape, name in case.slots if shape == "form"}
    if case.files:
        request["files"] = {name: ("sample.wav", b"\0" * 4096, "audio/wav") for name in case.files}
    if form or case.files:
        request["data"] = form
        return request
    body: dict[str, Any] | None = None
    if case.body_model is not None:
        schema = case.body_model.model_json_schema()
        body = {**_payload(schema, schema.get("$defs") or {}), **EXTRA_FIELDS.get(case.body_model.__name__, {})}
        for shape, name in case.slots:
            if shape in ("model", "dict"):  # a dict key beside a model: read from the raw body by a dependency
                _set(body, name, named(shape, name))
    elif case.body_name is not None or "dict" in case.shapes:
        body = {}
        for shape, name in case.slots:
            if shape == "dict":
                _set(body, name, named(shape, name))
    if body is not None and case.embed and case.body_model is not None:
        body = {case.body_name: body}
    if references and case.method in WRITE_METHODS:  # read from the raw body's top level by a dependency
        body = {**(body or {}), **references}
    if body is not None:
        request["json"] = body
    return request


class SideEffects:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def refuse(self, kind: str):
        def _record(*args, **kwargs):
            self.calls.append(f"{kind}: {args[1] if len(args) > 1 else args[:1]!r}"[:200])
            raise RuntimeError(f"{kind} is not performed in the Workspace route sweep")

        async def _record_async(*args, **kwargs):
            return _record(*args, **kwargs)

        return _record, _record_async


def record_side_effects(monkeypatch) -> SideEffects:
    import asyncio
    import subprocess

    import httpx

    effects = SideEffects()
    sync_http, async_http = effects.refuse("http")
    # The network transports only: the test client reaches the app through its ASGI transport.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_http)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_http)
    sync_process, async_process = effects.refuse("subprocess")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: sync_process(None, *args))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: sync_process(None, *args))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *args, **kwargs: async_process(None, *args))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", lambda *args, **kwargs: async_process(None, *args))
    return effects


async def snapshot(db) -> dict[str, str]:
    from app.services.speaker.diarization import _speaker_profiles

    hashes = {}
    for table in Base.metadata.sorted_tables:
        if table.name in REQUEST_LOG_TABLES:
            continue
        query = select(table)
        if table.name == "audit_log":
            query = query.where(table.c.resource_type.is_distinct_from(REQUEST_LOG_RESOURCE_TYPE))
        rows = sorted(repr(tuple(row)) for row in (await db.execute(query)).all())
        hashes[table.name] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    hashes["speaker_profiles"] = repr(sorted((key, [p.name for p in value]) for key, value in _speaker_profiles.items()))
    return hashes


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))


__all__ = ["RouteCase", "build_request", "changed", "record_side_effects", "refuses_an_unknown_workspace",
           "request_slots", "snapshot", "workspace_routes"]
