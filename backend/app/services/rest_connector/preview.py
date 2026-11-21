"""The change preview of a custom REST write: the request a person approves, as it would be sent.

A REST write has no tool of its own that could describe it (the operation is a database row), so the approval card
would say only "Execute tool rest__tickets__close_ticket". Like ``http_request``'s preview
(``tools/runtime_impl/_runtime_workspace_http``), the person sees what leaves the platform: the method, the API and
operation, the connection (by name), the URL with its path filled in, the query, the header *names*, the body, and
the data scope Octryx sets on it. Never a credential: the connection's auth is not applied here at all, a query value
or body field that looks like a secret (by name or by value) is masked, and header values are not shown.

The approval is bound to the call's arguments (``tool_approval_gate`` fingerprints them), and the scope is
server-owned and deterministic, so the request shown is the request that runs.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from ..redaction_policy import REDACTED_SECRET, is_sensitive_key, looks_like_secret_value, redact_secret_payload
from .authorization import (
    AppliedScope,
    NotGrantedError,
    ScopeError,
    caller_roles,
    matching_grants,
    resolve_scope,
    with_body_scope,
)
from .connections import connection_for_call
from .executor import find_operation
from .openapi_reader import FORBIDDEN_HEADERS
from .schema import BODY_PARAM, declared_parameters


def _shown(name: str, value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return REDACTED_SECRET if is_sensitive_key(name) or looks_like_secret_value(text) else text


async def _scope(db: Any, operation: Any, context: Any, workspace_id: str | None,
                 params: dict[str, Any]) -> AppliedScope | None:
    """The scope the call will run in; ``None`` when the executor will refuse it (shown as such)."""
    try:
        grants = matching_grants(operation, await caller_roles(db, context, workspace_id), workspace_id)
        return resolve_scope(grants, params)
    except (NotGrantedError, ScopeError):
        return None


def _request_parts(operation: Any, params: dict[str, Any], scope: AppliedScope | None
                   ) -> tuple[str, list[str], list[str], Any]:
    """Path (filled, encoded like the executor does), query lines, header names and the body (scope applied)."""
    declared = declared_parameters(operation)
    values = {name: param["fixed"] for name, param in declared.items() if param["fixed"] is not None}
    values.update({name: value for name, value in params.items() if name != BODY_PARAM})
    if scope is not None:
        values.update(scope.params)
    path = str(operation.path or "")
    query: list[str] = []
    headers: list[str] = []
    for name, param in declared.items():
        wire = param["wire"]  # shown as sent: ``$filter``, not the model's ``filter``
        if param["in"] == "path":
            shown = _shown(name, values[name]) if name in values else "{" + wire + "}"
            path = path.replace("{" + wire + "}", quote(shown, safe="[]{}") if name in values else shown)
        elif name in values and param["in"] == "query":
            query.append(f"{wire}={_shown(name, values[name])}")
        elif name in values and param["in"] == "header" and wire.lower() not in FORBIDDEN_HEADERS:
            headers.append(wire)
    body = params.get(BODY_PARAM)
    if scope is not None and scope.body:
        try:
            body = with_body_scope(body, scope.body)
        except ScopeError:
            pass  # the executor refuses this call; the body is shown as the model wrote it
    return (path if path.startswith("/") else f"/{path}"), query, headers, body


async def rest_change_preview(tool_name: str, params: dict[str, Any], context: Any) -> dict[str, Any] | None:
    """The preview payload of one ``rest__`` call, or ``None`` when the tool names no enabled operation."""
    from ..mcp_workspace_context import workspace_id_for_context

    db = getattr(context, "db", None)
    found = await find_operation(db, tool_name) if db is not None else None
    if found is None:
        return None
    definition, operation = found
    arguments = dict(params or {})
    workspace_id = workspace_id_for_context(context) or None
    connection = await connection_for_call(db, definition.id, workspace_id)
    scope = await _scope(db, operation, context, workspace_id, arguments)
    path, query, headers, body = _request_parts(operation, arguments, scope)
    method = str(operation.method or "").upper()
    base = str(connection.base_url).rstrip("/") if connection is not None else ""
    url = base + path + (("?" + "&".join(query)) if query else "")
    masked_body = redact_secret_payload(body) if body is not None else None
    details = [f"api: {definition.name}", f"operation: {operation.llm_name or operation.op_key}",
               f"request: {method} {url}"]
    if connection is not None:
        details.append(f"connection: {connection.name}")
    else:
        details.append("connection: none active for this Workspace (the call will be refused)")
    if headers:
        details.append(f"headers: {', '.join(headers)}")
    if masked_body is not None:
        details.append(f"body: {json.dumps(masked_body, ensure_ascii=False, default=str)}")
    if scope is None:
        details.append("scope: outside your access to this operation (the call will be refused)")
    elif scope.params or scope.body:
        fixed = [f"{name}={value}" for name, value in scope.params.items()]
        fixed += [f"body {name}={value}" for name, value in scope.body.items()]
        details.append(f"scope set by Octryx: {', '.join(fixed)}")
    return {
        "kind": "rest_request",
        "title": f"{method} {definition.name}: {operation.llm_name or operation.op_key}",
        "summary": f"{method} {url}",
        "method": method,
        "api": definition.name,
        "operation": operation.llm_name or operation.op_key,
        "connection": connection.name if connection is not None else None,
        "url": url,
        "header_names": headers,
        "body": masked_body,
        "details": details,
        # The arguments are shown above, masked; the chat card does not list them again unmasked.
        "fields_shown": True,
        "toolName": tool_name,
    }


__all__ = ["rest_change_preview"]
