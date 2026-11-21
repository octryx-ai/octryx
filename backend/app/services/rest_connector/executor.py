"""Running one ``rest__`` tool call: authorize, scope, authenticate, send, shape, audit.

Order matters and is fixed:

1. a write must fit the run's class, read from the stored operation (the gates before dispatch judged the
   same row; this repeats it so a stale view can never let a write through). Whether a person must approve it was
   decided by the central approval gate before dispatch (chat write plan, workflow policy, unattended runs, devices);
2. the caller's grants decide access and the data scope (``authorization``), from server-owned context only;
3. the arguments must fit the declared parameters; the scope's values (parameters and, for a JSON body, the grant's
   body paths) are then set last, so nothing the model sends can replace them (a contradicting value was already
   refused in step 2);
4. the URL is the connection's base URL plus the operation's path, the path parameters percent-encoded, and the
   host is checked again before sending: no argument can change where the call goes;
5. the answer is filtered to the scope and shaped; every call leaves one audit row (``runs``), a write with the
   approval or chat write plan that admitted it. Only a call that cannot write twice is retried (``retry_allowed``).

The tool result and the audit row never carry a secret: errors keep fixed codes and exception class names only,
and any credential value is redacted from the little text that is returned.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import RestApiDefinition, RestApiOperation
from ..change_preview import approval_ref_for
from ..error_facts import error_text
from ..outbound_egress import EgressRefusedError
from . import odata
from .auth import AuthConfigError, apply_auth, reserved_names
from .authorization import (
    AppliedScope,
    NotGrantedError,
    ScopeError,
    caller_roles,
    matching_grants,
    resolve_scope,
    with_body_scope,
)
from .authorization import scope_choices as grant_scope_choices
from .common import retry_allowed, split_tool_name, tool_name_for, write_capability
from .connections import connection_for_call, resolved_config
from .csrf import CsrfFetchError, csrf_for, fetch_token, session_values, token_required
from .http_call import RedirectRefusedError, response_json, rest_client, send
from .openapi_reader import FORBIDDEN_HEADERS
from .pagination import CursorError, next_cursor, open_url_cursor
from .response import ScopeFilterError, shape_body
from .runs import fail_run, run_payload, start_run, succeed_run
from .schema import (
    BODY_PARAM,
    ArgumentError,
    build_parameters_schema,
    check_arguments,
    cursor_param_name,
    declared_parameters,
)

MAX_ERROR_EXCERPT = 500


class CallRefusedError(Exception):
    def __init__(self, category: str, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status


async def find_operation(db: AsyncSession, tool_name: str) -> tuple[RestApiDefinition, RestApiOperation] | None:
    """The active definition and enabled operation behind a ``rest__`` tool name."""
    parts = split_tool_name(tool_name)
    if parts is None:
        return None
    definition_key, op_name = parts
    rows = (await db.execute(
        select(RestApiDefinition, RestApiOperation)
        .join(RestApiOperation, RestApiOperation.definition_id == RestApiDefinition.id)
        .where(RestApiDefinition.key == definition_key, RestApiDefinition.is_active.is_(True),
               RestApiOperation.enabled.is_(True))
    )).all()
    for definition, operation in rows:
        if (operation.llm_name or operation.op_key) == op_name:
            return definition, operation
    return None


def _workspace_id(context: Any) -> str | None:
    from ..mcp_workspace_context import workspace_id_for_context

    return workspace_id_for_context(context) or None


def _path(template: str, values: dict[str, Any], declared: dict[str, Any]) -> str:
    path = str(template or "")
    for name, param in declared.items():
        if param["in"] != "path":
            continue
        if name not in values:
            raise CallRefusedError("invalid_arguments", f"Missing required parameters: {name}")
        text = str(values[name])
        if text in {"", ".", ".."}:
            raise CallRefusedError("invalid_arguments", f"Invalid values for: {name}")
        path = path.replace("{" + param["wire"] + "}", quote(text, safe=""))
    return path if path.startswith("/") else f"/{path}"


def _request(
    client: httpx.AsyncClient, *, definition: RestApiDefinition, operation: RestApiOperation, base_url: str,
    arguments: dict[str, Any], scope: AppliedScope, auth_headers: dict[str, str], auth_query: dict[str, str],
    pagination: dict[str, Any], cursor: str | None, extra_headers: dict[str, str] | None = None,
) -> tuple[httpx.Request, int]:
    """The request of one call; parameter values go out under their wire names (``$filter`` for ``filter``)."""
    declared = declared_parameters(operation)
    values = {name: param["fixed"] for name, param in declared.items() if param["fixed"] is not None}
    values.update({name: value for name, value in arguments.items() if name != BODY_PARAM})
    values.update(scope.params)  # last: the scope always holds
    reserved = reserved_names(definition.auth or {})
    query: dict[str, Any] = {}
    headers: dict[str, str] = {"Accept": "application/json"}
    for name, param in declared.items():
        wire = param["wire"]
        if name not in values or wire.lower() in reserved:
            continue
        if param["in"] == "query":
            value = values[name]
            query[wire] = ",".join(str(item) for item in value) if isinstance(value, list) and not param["explode"] \
                else value
        elif param["in"] == "header" and wire.lower() not in FORBIDDEN_HEADERS:
            headers[wire] = str(values[name])
    url = base_url.rstrip("/") + _path(operation.path, values, declared)
    offset = 0
    kind = pagination["type"]
    if cursor and kind in {"next_url", "link_header"}:
        try:
            url = open_url_cursor(cursor, operation.id, base_url)
        except CursorError as refused:
            raise CallRefusedError("invalid_cursor", str(refused)) from None
        # The next URL carries the API's own query; only the scope's query values are set again on it.
        query = {declared[name]["wire"]: value for name, value in scope.params.items()
                 if declared.get(name, {}).get("in") == "query"}
    elif cursor and kind == "cursor":
        query[pagination["cursor_param"]] = cursor
    elif kind == "offset":
        if cursor:
            if not str(cursor).isdigit():
                raise CallRefusedError("invalid_cursor", "The cursor is not one this operation returned.")
            offset = int(cursor)
        query[pagination["offset_param"]] = offset
        query.setdefault(pagination["limit_param"], pagination["page_size"])
    query.update(auth_query)
    headers.update(auth_headers)
    headers.update(extra_headers or {})
    if httpx.URL(url).host != httpx.URL(base_url).host:
        raise CallRefusedError("host_changed", "The call would leave the connection's host; it was not sent.")
    body = arguments.get(BODY_PARAM)
    if scope.body:
        body = with_body_scope(body, scope.body)  # last: the grant's body fields always hold
    # Merged, not replaced: a followed next URL keeps the API's own query (httpx 0.28 ``params=`` replaces it).
    target = httpx.URL(url).copy_merge_params(query) if query else httpx.URL(url)
    request = client.build_request(operation.method.upper(), target, headers=headers,
                                   json=body if body is not None else None)
    return request, offset


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


async def _caller_grants(db: AsyncSession, operation: RestApiOperation, context: Any,
                         workspace_id: str | None) -> list[Any]:
    return matching_grants(operation, await caller_roles(db, context, workspace_id), workspace_id)


def _refused_scope(operation: RestApiOperation, grants: list[Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """The audit of a scope refusal: the scoped parameters the call asked for, and every scope the caller holds."""
    scoped = sorted({name for grant in grants for name in grant.scope})
    return {"refused": True,
            "requested": {name: arguments[name] for name in scoped if name in arguments},
            "allowed": [{"role": grant.role, "params": dict(grant.scope), "result_filter": grant.result_filter}
                        for grant in grants if grant.scoped]}


def check_write_class(definition: RestApiDefinition, operation: RestApiOperation, context: Any) -> None:
    """A write runs only in a run whose class covers the operation's (``deliver`` unless the admin said ``change``).

    The gates before dispatch decided this from the in-process view of the operation (``rest_tool_classes``); here
    it is decided again from the stored row, and the view is brought up to date for the next call."""
    from ...tools.definitions.rest_tool_classes import remember_rest_tool
    from ..run_capability.chat_writes import chat_connector_write_permitted
    from ..run_capability.classes import capability_covers, enforced_run_capability_class

    required = write_capability(operation)
    tool_name = tool_name_for(definition.key, operation.llm_name or operation.op_key)
    remember_rest_tool(tool_name, required)
    if required is None:
        return
    run_class = enforced_run_capability_class(context)
    if run_class is None or capability_covers(run_class, required):
        return
    if chat_connector_write_permitted(tool_name, context):
        return  # a chat write: admitted by the person's write plan at the gate
    raise CallRefusedError("capability_exceeded", f"This run is '{run_class}'; this operation writes and needs "
                                                  f"'{required}'. Only a workflow declaring '{required}' may call it.")


async def _authorize(db: AsyncSession, operation: RestApiOperation, context: Any, workspace_id: str | None,
                     arguments: dict[str, Any]) -> tuple[AppliedScope, list[Any]]:
    grants = matching_grants(operation, await caller_roles(db, context, workspace_id), workspace_id)
    try:
        return resolve_scope(grants, arguments), grants
    except NotGrantedError as refused:
        raise CallRefusedError("not_granted", str(refused)) from None
    except ScopeError as refused:
        raise CallRefusedError("scope_violation", str(refused)) from None


def _checked_arguments(operation: RestApiOperation, grants: list[Any], scope: AppliedScope,
                       arguments: dict[str, Any], pagination: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    schema = build_parameters_schema(operation, scope_choices=grant_scope_choices(grants),
                                     paginated=pagination["type"] != "none")
    # A scoped value the model repeated (it fits the scope, step 2) is not a free parameter of this caller.
    candidate = {name: value for name, value in arguments.items()
                 if not (name in scope.params and name not in schema["properties"])}
    try:
        checked = check_arguments(schema, candidate)
    except ArgumentError as refused:
        raise CallRefusedError("invalid_arguments", str(refused)) from None
    cursor = checked.pop(cursor_param_name(declared_parameters(operation)), None) if pagination["type"] != "none" \
        else None
    return checked, cursor


async def _csrf_token(client: httpx.AsyncClient, csrf: dict[str, Any], *, base_url: str, auth: Any,
                      timeout: float, secrets: list[str]) -> dict[str, str]:
    try:
        token = await fetch_token(client, base_url=base_url, csrf=csrf, auth_headers=auth.headers,
                                  auth_query=auth.query, timeout=timeout)
    except CsrfFetchError as refused:
        raise CallRefusedError("csrf_fetch_failed", str(refused)) from None
    secrets.extend(session_values(client, token))
    return {csrf["header"]: token}


async def _send_call(client: httpx.AsyncClient, build: Any, *, definition: RestApiDefinition,
                     operation: RestApiOperation, base_url: str, auth: Any, timeout: float, secrets: list[str]
                     ) -> tuple[httpx.Response, int, int]:
    """Sends the call; a write of a definition with ``auth.csrf`` first fetches its token (``csrf``).

    A 403 ``x-csrf-token: Required`` refetches once and sends once more: the first write was refused before it
    did anything, so sending it again cannot write twice."""
    csrf = csrf_for(definition.auth, operation.method)
    extra = await _csrf_token(client, csrf, base_url=base_url, auth=auth, timeout=timeout, secrets=secrets) \
        if csrf else {}
    request, offset = build(extra)
    response, retries = await send(client, request, timeout=timeout, retryable=retry_allowed(operation))
    if csrf and token_required(response, csrf):
        await response.aclose()
        extra = await _csrf_token(client, csrf, base_url=base_url, auth=auth, timeout=timeout, secrets=secrets)
        request, offset = build(extra)
        response, more = await send(client, request, timeout=timeout, retryable=retry_allowed(operation))
        retries += 1 + more
    return response, retries, offset


async def _call(db: AsyncSession, *, definition: RestApiDefinition, operation: RestApiOperation, context: Any,
                workspace_id: str | None, arguments: dict[str, Any], run: Any, secrets: list[str]) -> dict[str, Any]:
    check_write_class(definition, operation, context)
    try:
        scope, grants = await _authorize(db, operation, context, workspace_id, arguments)
    except CallRefusedError as refused:
        if refused.category == "scope_violation":
            # What was asked and what the caller's grants allow, so the audit shows why (never an empty scope).
            run.scope_json = _refused_scope(operation, await _caller_grants(db, operation, context, workspace_id),
                                            arguments)
        raise
    run.scope_json = scope.audit()
    records_path, pagination, _source = odata.effective_response(definition, operation)
    checked, cursor = _checked_arguments(operation, grants, scope, arguments, pagination)
    connection = await connection_for_call(db, definition.id, workspace_id)
    if connection is None:
        raise CallRefusedError("no_connection", "This API has no active connection for this Workspace or the "
                                                "platform. A platform admin can add one (Connections › REST APIs).")
    run.connection_id = connection.id
    config = await resolved_config(db, connection)
    timeout = float(definition.timeout_seconds or 30)
    async with rest_client(timeout) as client:
        try:
            auth = await apply_auth(client, connection_id=connection.id, auth=dict(definition.auth or {}),
                                    config=config)
        except AuthConfigError as refused:
            raise CallRefusedError("auth_config", str(refused)) from None
        secrets.extend(auth.secret_values())

        def build(extra_headers: dict[str, str]) -> tuple[httpx.Request, int]:
            try:
                return _request(client, definition=definition, operation=operation, base_url=connection.base_url,
                                arguments=checked, scope=scope, auth_headers=auth.headers, auth_query=auth.query,
                                pagination=pagination, cursor=cursor, extra_headers=extra_headers)
            except ScopeError as refused:
                raise CallRefusedError("scope_violation", str(refused)) from None

        build({})  # refuses a call outside the scope before any request, the CSRF fetch included
        response, retries, offset = await _send_call(client, build, definition=definition, operation=operation,
                                                     base_url=connection.base_url, auth=auth, timeout=timeout,
                                                     secrets=secrets)
    body = response_json(response)
    if response.status_code >= 400:
        excerpt = _redact(str(body or "")[:MAX_ERROR_EXCERPT], secrets)
        raise CallRefusedError("http_error", f"The API answered HTTP {response.status_code}. {excerpt}".strip(),
                               http_status=response.status_code)
    try:
        shaped, kept, dropped = shape_body(body, records_path=records_path, result_filter=scope.result_filter,
                                           response_select=list(operation.response_select or []))
    except ScopeFilterError as refused:
        raise CallRefusedError("scope_filter_unavailable", str(refused), http_status=response.status_code) from None
    cursor_out = next_cursor(pagination, body=body, response=response, operation_id=operation.id, offset=offset,
                             record_count=kept + dropped) if pagination["type"] != "none" else None
    await succeed_run(db, run, http_status=response.status_code, record_count=kept, dropped_count=dropped)
    return {
        "api": definition.name,
        "operation": operation.llm_name or operation.op_key,
        "writes": write_capability(operation) is not None,
        "status_code": response.status_code,
        "data": shaped,
        "record_count": kept,
        "dropped_out_of_scope": dropped,
        "next_cursor": cursor_out,
        "scope": {"params": dict(scope.params), "result_filter": scope.result_filter},
        "retries": retries,
        "run": run_payload(run),
    }


async def execute_rest_tool(tool_name: str, params: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """The ``rest__`` tool entry point (``tools/registry``); every call that names an operation is audited."""
    db = getattr(context, "db", None)
    if db is None:
        return {"error": "REST API tools require an active platform database session."}
    found = await find_operation(db, tool_name)
    if found is None:
        return {"error": f"Unknown REST API tool: {tool_name}"}
    definition, operation = found
    return await run_operation(db, definition=definition, operation=operation, tool_name=tool_name, params=params,
                               context=context)


async def run_operation(db: AsyncSession, *, definition: RestApiDefinition, operation: RestApiOperation,
                        tool_name: str, params: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """One audited call of ``operation`` (the tool path and the admin test call share it)."""
    workspace_id = _workspace_id(context)
    arguments = dict(params or {})
    run = await start_run(db, definition=definition, operation=operation, tool_name=tool_name, context=context,
                          workspace_id=workspace_id, arguments=arguments,
                          admitted_by=approval_ref_for(context, tool_name, arguments))
    secrets: list[str] = []
    try:
        return await _call(db, definition=definition, operation=operation, context=context,
                           workspace_id=workspace_id, arguments=arguments, run=run, secrets=secrets)
    except CallRefusedError as refused:
        message = _redact(str(refused), secrets)
        await fail_run(db, run, category=refused.category, message=message, http_status=refused.http_status,
                       secrets=secrets)
        return {"error": message, "code": refused.category, "run": run_payload(run)}
    except EgressRefusedError as refused:
        # The reason is a fixed word (``private_address_not_allowlisted``); the host is never named.
        message = f"The egress policy refused the target ({refused.reason}). A platform admin can add an on-prem " \
                  "host to the private-host allowlist of the connection type 'custom_rest'."
        await fail_run(db, run, category="egress_refused", message=message)
        return {"error": message, "code": "egress_refused", "run": run_payload(run)}
    except (RedirectRefusedError, httpx.HTTPError, ValueError, OSError) as exc:
        # Transport errors can name hosts or URLs with a query key: only the fixed code and class name are kept.
        failure = error_text("rest_call_failed", exc)
        await fail_run(db, run, category="request_failed", message=failure)
        return {"error": f"The REST call failed. {failure}", "code": "request_failed", "run": run_payload(run)}


__all__ = ["CallRefusedError", "check_write_class", "execute_rest_tool", "find_operation", "run_operation"]
