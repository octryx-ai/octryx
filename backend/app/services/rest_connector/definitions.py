"""Admin side of custom REST definitions and their operations."""

from __future__ import annotations

import difflib
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import RestApiCallRun, RestApiConnection, RestApiDefinition, RestApiOperation
from ...time_utils import ensure_utc
from ..secret.release import config_secret_refs, release_unreferenced_secrets
from . import odata
from .authorization import FIELD_PATH_RE, normalize_grants
from .common import (
    AUTH_SCHEMES,
    IDEMPOTENT_CANDIDATE_METHODS,
    METHODS,
    WRITE_CAPABILITIES,
    http_url_problem,
    is_read_operation,
    tool_name_for,
    validate_key,
    validate_op_name,
    write_capability,
)
from .csrf import normalize_csrf
from .openapi_reader import FORBIDDEN_HEADERS, OpenApiError, read_openapi
from .pagination import normalize_pagination
from .param_names import alias_parameters
from .schema import clean_schema, declared_parameters

MANY_OPERATIONS = 25
SIMILAR_DESCRIPTION_RATIO = 0.9
MAX_TIMEOUT_SECONDS = 300


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value else None


def serialize_operation(definition: RestApiDefinition, operation: RestApiOperation) -> dict[str, Any]:
    records_path, pagination, preset_source = odata.effective_response(definition, operation)
    return {
        "id": operation.id,
        "op_key": operation.op_key,
        "tool_name": tool_name_for(definition.key, operation.llm_name or operation.op_key),
        "method": operation.method,
        "path": operation.path,
        "summary": operation.summary or "",
        "parameters": list(operation.parameters or []),
        "request_body": operation.request_body,
        "enabled": bool(operation.enabled),
        "read_only": bool(operation.read_only),
        "is_read": is_read_operation(operation.method, operation.read_only),
        "llm_name": operation.llm_name or "",
        "llm_description": operation.llm_description or "",
        "params_overlay": dict(operation.params_overlay or {}),
        "grants": list(operation.grants or []),
        "response_select": list(operation.response_select or []),
        "records_path": records_path or "",
        "pagination": pagination,
        # The effective preset and where it comes from: the operation's own, the definition's default, or none.
        "preset": odata.preset_of(records_path, pagination),
        "preset_source": preset_source,
        "unsupported": odata.unsupported_reason(operation.path, operation.request_body) or "",
        "capability": write_capability(operation),
        "declared_capability": operation.capability or "",
        "idempotent": bool(operation.idempotent),
        "scope_warnings": scope_bypass_warnings(operation),
    }


def serialize_definition(definition: RestApiDefinition, operations: list[RestApiOperation] | None = None
                         ) -> dict[str, Any]:
    payload = {
        "id": definition.id,
        "key": definition.key,
        "name": definition.name,
        "description": definition.description or "",
        "source_kind": definition.source_kind,
        "source_url": definition.source_url or "",
        "spec_version": definition.spec_version or "",
        "servers": list(definition.servers or []),
        "auth": dict(definition.auth or {}),
        "timeout_seconds": int(definition.timeout_seconds or 30),
        "default_preset": definition.default_preset or "",
        "is_active": bool(definition.is_active),
        "created_at": _iso(definition.created_at),
        "updated_at": _iso(definition.updated_at),
    }
    if operations is not None:
        payload["operations"] = [serialize_operation(definition, operation) for operation in operations]
        payload["warnings"] = definition_warnings(operations)
    return payload


def _operation_label(operation: RestApiOperation) -> str:
    return operation.llm_name or operation.op_key


def per_operation_warnings(operation: RestApiOperation) -> list[str]:
    warnings: list[str] = []
    if operation.enabled and not operation.grants:
        warnings.append(f"'{_operation_label(operation)}': enabled without grants: no one can call it until a role "
                        "is granted.")
    return [*warnings, *(f"'{_operation_label(operation)}': {warning}" for warning in scope_bypass_warnings(operation))]


def definition_warnings(operations: list[RestApiOperation]) -> list[str]:
    return [*operation_warnings(operations),
            *(w for operation in operations for w in per_operation_warnings(operation))]


def operation_warnings(operations: list[RestApiOperation]) -> list[str]:
    enabled = [operation for operation in operations if operation.enabled]
    warnings: list[str] = []
    if len(enabled) > MANY_OPERATIONS:
        warnings.append(f"{len(enabled)} operations are enabled; above {MANY_OPERATIONS} models choose less reliably "
                        "between similar tools. Consider enabling only what agents need.")
    described = [
        (operation.llm_name or operation.op_key, (operation.llm_description or operation.summary or "").strip())
        for operation in enabled
    ]
    for index, (name, text) in enumerate(described):
        for other_name, other_text in described[index + 1:]:
            if text and other_text and difflib.SequenceMatcher(None, text.lower(), other_text.lower()).ratio() \
                    >= SIMILAR_DESCRIPTION_RATIO:
                warnings.append(f"'{name}' and '{other_name}' have nearly the same description; the model may not "
                                "tell them apart.")
    return warnings


def _normalize_auth(raw: Any) -> dict[str, Any]:
    auth = dict(raw) if isinstance(raw, dict) else {}
    scheme = str(auth.get("scheme") or "none")
    if scheme not in AUTH_SCHEMES:
        raise HTTPException(status_code=400, detail=f"auth.scheme must be one of {', '.join(AUTH_SCHEMES)}")
    normalized: dict[str, Any] = {"scheme": scheme}
    for name in ("header_name", "query_name", "token_url", "source_scheme"):
        if str(auth.get(name) or "").strip():
            normalized[name] = str(auth[name]).strip()
    if auth.get("scopes"):
        normalized["scopes"] = [str(item) for item in auth["scopes"]]
    if scheme == "api_key_header" and normalized.get("header_name", "").lower() in {"host", "cookie"}:
        raise HTTPException(status_code=400, detail="auth.header_name may not be Host or Cookie")
    csrf = normalize_csrf(auth.get("csrf"))
    if csrf:
        normalized["csrf"] = csrf
    return normalized


def _servers(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail=[{"loc": ["body", "servers"], "msg": "servers must be a list",
                                                      "type": "value_error"}])
    servers = []
    for index, item in enumerate(raw):
        url = str(item or "").strip().rstrip("/")
        problem = http_url_problem(url)
        if problem:
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "servers", index], "msg": f"servers[{index}] {problem}: '{url}'",
                "type": "value_error"}])
        servers.append(url)
    return servers


def _timeout(raw: Any) -> int:
    try:
        value = int(raw if raw not in (None, "") else 30)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="timeout_seconds must be an integer") from None
    if not 1 <= value <= MAX_TIMEOUT_SECONDS:
        raise HTTPException(status_code=400, detail=f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}")
    return value


async def _load(db: AsyncSession, definition_id: str) -> RestApiDefinition:
    definition = await db.get(RestApiDefinition, definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="REST API definition not found")
    return definition


async def _operations(db: AsyncSession, definition_id: str) -> list[RestApiOperation]:
    return list((await db.execute(
        select(RestApiOperation).where(RestApiOperation.definition_id == definition_id)
        .order_by(RestApiOperation.op_key)
    )).scalars().all())


async def _key_free(db: AsyncSession, key: str) -> None:
    if (await db.execute(select(RestApiDefinition.id).where(RestApiDefinition.key == key))).scalar():
        raise HTTPException(status_code=409, detail=f"A REST API with the key '{key}' exists")


def _parameters(raw: Any) -> list[dict[str, Any]]:
    parameters = []
    for entry in raw or []:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            raise HTTPException(status_code=400, detail="each parameter needs a name")
        location = str(entry.get("in") or "query")
        if location not in {"path", "query", "header"}:
            raise HTTPException(status_code=400, detail="parameter 'in' must be path, query or header")
        if location == "header" and str(entry["name"]).lower() in FORBIDDEN_HEADERS:
            continue
        parameters.append({"name": str(entry["name"]).strip(), "in": location,
                           "required": bool(entry.get("required")) or location == "path",
                           "description": str(entry.get("description") or ""),
                           "schema": clean_schema(entry.get("schema") or {"type": "string"})})
    return alias_parameters(parameters)


def _new_operation(definition_id: str, raw: dict[str, Any]) -> RestApiOperation:
    method = str(raw.get("method") or "GET").upper()
    if method not in METHODS:
        raise HTTPException(status_code=400, detail=f"method must be one of {', '.join(METHODS)}")
    path = str(raw.get("path") or "").strip()
    if not path.startswith("/") or "://" in path:
        raise HTTPException(status_code=400, detail="path must be a path starting with '/', never a URL")
    return RestApiOperation(
        definition_id=definition_id,
        op_key=validate_op_name(raw.get("op_key")),
        method=method,
        path=path,
        summary=str(raw.get("summary") or "")[:2000],
        parameters=_parameters(raw.get("parameters")),
        request_body=raw.get("request_body") if isinstance(raw.get("request_body"), dict) else None,
        enabled=False,
        read_only=bool(raw.get("read_only", method in {"GET", "HEAD"})),
        params_overlay={}, grants=[], response_select=[], pagination={"type": "none"},
    )


async def list_definitions(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(RestApiDefinition).order_by(RestApiDefinition.key))).scalars().all()
    from ...models import RestApiConnection

    operations: dict[str, list[RestApiOperation]] = {}
    for operation in (await db.execute(select(RestApiOperation))).scalars().all():
        operations.setdefault(operation.definition_id, []).append(operation)
    connection_counts = dict((await db.execute(
        select(RestApiConnection.definition_id, func.count()).group_by(RestApiConnection.definition_id)
    )).all())
    listed = []
    for row in rows:
        ops = operations.get(row.id, [])
        listed.append({**serialize_definition(row), "operations": len(ops),
                       "enabled_operations": sum(1 for op in ops if op.enabled),
                       "connections": int(connection_counts.get(row.id, 0)),
                       "warnings": len(definition_warnings(ops))})
    return listed


async def get_definition(db: AsyncSession, definition_id: str) -> dict[str, Any]:
    definition = await _load(db, definition_id)
    return serialize_definition(definition, await _operations(db, definition_id))


async def create_definition(db: AsyncSession, payload: dict[str, Any], *, actor_user_id: str | None
                            ) -> dict[str, Any]:
    key = validate_key(payload.get("key"))
    await _key_free(db, key)
    definition = RestApiDefinition(
        key=key,
        name=str(payload.get("name") or key).strip()[:160],
        description=str(payload.get("description") or "").strip() or None,
        source_kind="manual",
        servers=_servers(payload.get("servers")),
        auth=_normalize_auth(payload.get("auth")),
        timeout_seconds=_timeout(payload.get("timeout_seconds")),
        is_active=bool(payload.get("is_active", True)),
        created_by=actor_user_id,
    )
    db.add(definition)
    await db.flush()
    for raw in payload.get("operations") or []:
        db.add(_new_operation(definition.id, raw))
    await db.commit()
    return await get_definition(db, definition.id)


async def _fetch_spec(url: str) -> str:
    from ..outbound_egress.public_web import public_web_client

    async with public_web_client(timeout=30.0) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=400, detail=f"Fetching the OpenAPI document answered HTTP {response.status_code}"
        )
    return response.text


async def import_definition(db: AsyncSession, payload: dict[str, Any], *, actor_user_id: str | None
                            ) -> dict[str, Any]:
    key = validate_key(payload.get("key"))
    await _key_free(db, key)
    source_url = str(payload.get("spec_url") or "").strip() or None
    text = str(payload.get("spec_text") or "")
    if not text and source_url:
        text = await _fetch_spec(source_url)
    try:
        spec = read_openapi(text)
    except OpenApiError as refused:
        raise HTTPException(status_code=400, detail=str(refused)) from None
    definition = RestApiDefinition(
        key=key,
        name=str(payload.get("name") or spec["title"] or key).strip()[:160],
        description=spec["description"][:4000] or None,
        source_kind="openapi",
        source_url=source_url,
        spec_version=spec["spec_version"],
        servers=spec["servers"],
        auth=spec["auth"],
        default_preset=spec.get("default_preset") or None,
        timeout_seconds=_timeout(payload.get("timeout_seconds")),
        is_active=True,
        created_by=actor_user_id,
    )
    db.add(definition)
    await db.flush()
    for operation in spec["operations"]:
        db.add(RestApiOperation(
            definition_id=definition.id, op_key=operation["op_key"], method=operation["method"],
            path=operation["path"], summary=operation["summary"][:2000], parameters=operation["parameters"],
            request_body=operation["request_body"], enabled=False, read_only=operation["read_only"],
            params_overlay={}, grants=[], response_select=[], records_path=operation["records_path"],
            pagination=operation["pagination"],
        ))
    await db.commit()
    result = await get_definition(db, definition.id)
    result["warnings"] = [*spec["warnings"], *result["warnings"]]
    return result


async def update_definition(db: AsyncSession, definition_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    definition = await _load(db, definition_id)
    if "name" in payload:
        definition.name = str(payload.get("name") or definition.name).strip()[:160]
    if "description" in payload:
        definition.description = str(payload.get("description") or "").strip() or None
    if "servers" in payload:
        definition.servers = _servers(payload.get("servers"))
    if "auth" in payload:
        definition.auth = _normalize_auth(payload.get("auth"))
    if "timeout_seconds" in payload:
        definition.timeout_seconds = _timeout(payload.get("timeout_seconds"))
    if "is_active" in payload:
        definition.is_active = bool(payload.get("is_active"))
    if "default_preset" in payload:
        definition.default_preset = _default_preset(payload.get("default_preset"))
    await db.commit()
    return await get_definition(db, definition_id)


def _default_preset(raw: Any) -> str | None:
    name = str(raw or "").strip()
    if name and name not in odata.PRESETS:
        raise HTTPException(status_code=422, detail={"field": "default_preset",
                                                     "message": f"must be one of {', '.join(odata.PRESETS)} or empty"})
    return name or None


async def delete_definition(db: AsyncSession, definition_id: str) -> dict[str, Any]:
    definition = await _load(db, definition_id)
    connections = (await db.execute(
        select(RestApiConnection).where(RestApiConnection.definition_id == definition_id)
    )).scalars().all()
    secret_ids: set[str] = set()
    for connection in connections:
        secret_ids |= config_secret_refs(dict(connection.config or {}))
    recorded = int((await db.execute(
        select(func.count()).select_from(RestApiCallRun).where(RestApiCallRun.definition_id == definition_id)
    )).scalar_one())
    await db.execute(delete(RestApiConnection).where(RestApiConnection.definition_id == definition_id))
    await db.execute(delete(RestApiOperation).where(RestApiOperation.definition_id == definition_id))
    await db.delete(definition)
    await db.flush()
    released = await release_unreferenced_secrets(db, secret_ids)
    await db.commit()
    return {"status": "deleted", "recorded_calls_kept": recorded, "stored_entries": released.to_payload()}


async def add_operation(db: AsyncSession, definition_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    definition = await _load(db, definition_id)
    operation = _new_operation(definition_id, payload)
    if any(existing.op_key == operation.op_key for existing in await _operations(db, definition_id)):
        raise HTTPException(status_code=409, detail=f"The operation key '{operation.op_key}' exists")
    db.add(operation)
    await db.commit()
    return serialize_operation(definition, operation)


def _response_select(raw: Any) -> list[str]:
    paths = [str(item).strip() for item in raw or [] if str(item).strip()]
    for path in paths:
        if not FIELD_PATH_RE.fullmatch(path):
            raise HTTPException(status_code=400, detail=f"response_select: not a dotted field path: {path}")
    return paths


def _overlay(raw: Any, declared: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="params_overlay must be an object")
    overlay: dict[str, Any] = {}
    for name, entry in raw.items():
        if name not in declared or not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"params_overlay names an undeclared parameter: {name}")
        overlay[name] = {key: entry[key] for key in ("description", "hidden", "value") if key in entry}
    return overlay


async def _unique_llm_name(db: AsyncSession, operation: RestApiOperation, name: str) -> None:
    for other in await _operations(db, operation.definition_id):
        if other.id != operation.id and (other.llm_name or other.op_key) == name:
            raise HTTPException(status_code=409, detail=f"Another operation of this API is already named '{name}'")


async def update_operation(db: AsyncSession, definition_id: str, operation_id: str, payload: dict[str, Any]
                           ) -> dict[str, Any]:
    definition = await _load(db, definition_id)
    operation = await db.get(RestApiOperation, operation_id)
    if operation is None or operation.definition_id != definition_id:
        raise HTTPException(status_code=404, detail="REST API operation not found")
    if "params_overlay" in payload:
        operation.params_overlay = _overlay(payload.get("params_overlay") or {}, declared_parameters(operation))
    declared = declared_parameters(operation)
    if "llm_name" in payload:
        name = str(payload.get("llm_name") or "").strip()
        if name:
            validate_op_name(name, field="llm_name")
            await _unique_llm_name(db, operation, name)
        operation.llm_name = name or None
    if "llm_description" in payload:
        operation.llm_description = str(payload.get("llm_description") or "").strip() or None
    if "read_only" in payload:
        operation.read_only = bool(payload.get("read_only"))
    if "grants" in payload:
        operation.grants = normalize_grants(payload.get("grants"), declared=declared,
                                            has_body=isinstance(operation.request_body, dict))
    if "capability" in payload:
        operation.capability = _capability(payload.get("capability"))
    if "idempotent" in payload:
        operation.idempotent = _idempotent(operation, payload.get("idempotent"))
    if "response_select" in payload:
        operation.response_select = _response_select(payload.get("response_select"))
    if payload.get("preset"):
        _apply_preset(operation, payload["preset"])  # a preset name, "none" or "inherit"
    if "records_path" in payload:
        records_path = str(payload.get("records_path") or "").strip()
        if records_path and not FIELD_PATH_RE.fullmatch(records_path):
            raise HTTPException(status_code=400, detail="records_path must be a dotted field path")
        operation.records_path = records_path or None
    if "pagination" in payload:
        try:
            operation.pagination = normalize_pagination(payload.get("pagination"))
        except (TypeError, ValueError) as refused:
            raise HTTPException(status_code=400, detail=str(refused)) from None
    if "enabled" in payload:
        operation.enabled = _enabled(operation, payload.get("enabled"))
    await db.commit()
    _remember(definition, operation)
    result = serialize_operation(definition, operation)
    result["warnings"] = [*operation_warnings(await _operations(db, definition_id)), *per_operation_warnings(operation)]
    return result


def _apply_preset(operation: RestApiOperation, name: Any) -> None:
    if str(name) == "inherit":
        operation.records_path, operation.pagination = None, {}
        return
    if str(name) == "none":
        operation.records_path, operation.pagination = None, {"type": "none"}
        return
    if str(name) not in odata.PRESETS:
        raise HTTPException(status_code=400,
                            detail=f"preset must be one of {', '.join(odata.PRESETS)}, none or inherit")
    values = odata.preset(str(name))
    operation.records_path = values["records_path"]
    operation.pagination = normalize_pagination(values["pagination"])


def _enabled(operation: RestApiOperation, raw: Any) -> bool:
    value = bool(raw)
    if value and odata.unsupported_reason(operation.path, operation.request_body) == odata.UNSUPPORTED_BATCH:
        raise HTTPException(status_code=400, detail="This is an OData $batch operation, which Octryx does not run: "
                                                    "a batch carries several requests past the per-call grants and "
                                                    "audit. Enable the single operations instead.")
    return value


def _remember(definition: RestApiDefinition, operation: RestApiOperation) -> None:
    from ...tools.definitions.rest_tool_classes import remember_rest_tool

    capability = write_capability(operation) if operation.enabled and definition.is_active else None
    remember_rest_tool(tool_name_for(definition.key, operation.llm_name or operation.op_key), capability)


def _capability(raw: Any) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value not in WRITE_CAPABILITIES:
        raise HTTPException(status_code=400, detail=f"capability must be one of {', '.join(WRITE_CAPABILITIES)}")
    return value


def _idempotent(operation: RestApiOperation, raw: Any) -> bool:
    value = bool(raw)
    if value and str(operation.method or "").upper() not in IDEMPOTENT_CANDIDATE_METHODS:
        raise HTTPException(status_code=400, detail="idempotent can be set for PUT and DELETE operations only")
    return value


def scope_bypass_warnings(operation: RestApiOperation) -> list[str]:
    from .schema import BODY_PARAM, declared_parameters

    declared = declared_parameters(operation)
    warnings: list[str] = []
    for grant in operation.grants or []:
        scope = dict((grant or {}).get("scope") or {}) if isinstance(grant, dict) else {}
        if not scope or (grant or {}).get("result_filter"):
            continue
        free = sorted(name for name, param in declared.items()
                      if name not in scope and not param["hidden"] and param["fixed"] is None
                      and param["in"] in {"query", "header"})
        if operation.method.upper() == "POST" or BODY_PARAM in declared:
            free.append("the request body")
        if free:
            warnings.append(
                f"The grant for role '{grant.get('role')}' limits {', '.join(sorted(scope))} but has no result filter, "
                f"and the model can still set {', '.join(free)}. If the API lets those widen the answer, the scope "
                "does not hold: add a result filter (records outside it are dropped) or fix/hide those parameters.")
    return warnings


async def delete_operation(db: AsyncSession, definition_id: str, operation_id: str) -> dict[str, Any]:
    operation = await db.get(RestApiOperation, operation_id)
    if operation is None or operation.definition_id != definition_id:
        raise HTTPException(status_code=404, detail="REST API operation not found")
    await db.delete(operation)
    await db.commit()
    return {"status": "deleted"}


async def recent_calls(db: AsyncSession, *, limit: int = 50, definition_id: str | None = None,
                       operation_id: str | None = None) -> list[dict[str, Any]]:
    from ...models import Project, User

    query = select(RestApiCallRun)
    if definition_id:
        query = query.where(RestApiCallRun.definition_id == definition_id)
    if operation_id:
        query = query.where(RestApiCallRun.operation_id == operation_id)
    rows = (await db.execute(
        query.order_by(RestApiCallRun.started_at.desc()).limit(max(1, min(limit, 200)))
    )).scalars().all()
    user_ids = {run.actor_user_id for run in rows if run.actor_user_id}
    workspace_ids = {run.project_id for run in rows if run.project_id}
    users = {user.id: user.display_name or user.username for user in (await db.execute(
        select(User).where(User.id.in_(user_ids)))).scalars()} if user_ids else {}
    workspaces = dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(workspace_ids)))).all()
                      ) if workspace_ids else {}
    operation_ids = {run.operation_id for run in rows if run.operation_id}
    # Whether each call's operation writes (None once the operation is removed); the admin filters writes by it.
    writes = {operation.id: not is_read_operation(operation.method, operation.read_only) for operation in (
        await db.execute(select(RestApiOperation).where(RestApiOperation.id.in_(operation_ids)))).scalars()
    } if operation_ids else {}
    return [{
        "error": run.error or "", "user_name": users.get(run.actor_user_id),
        "workspace_name": workspaces.get(run.project_id),
        "id": run.id, "tool_name": run.tool_name, "identity": run.identity, "status": run.status,
        "failure_category": run.failure_category or "", "http_status": run.http_status,
        "scope": dict(run.scope_json or {}), "records": int(run.record_count or 0),
        "dropped_out_of_scope": int(run.dropped_count or 0), "duration_ms": run.duration_ms,
        "user_id": run.actor_user_id, "workspace_id": run.project_id, "connection_id": run.connection_id,
        "definition_id": run.definition_id, "operation_id": run.operation_id,
        "started_at": _iso(run.started_at),
        # What admitted a write and the chat it ran in, so the audit can open where it was decided.
        "approval_id": run.approval_id, "write_plan_id": run.write_plan_id, "session_id": run.session_id,
        "write": writes.get(run.operation_id),
    } for run in rows]


async def admin_test_call(db: AsyncSession, definition_id: str, operation_id: str, payload: dict[str, Any], *,
                    admin_user_id: str) -> dict[str, Any]:
    import uuid

    from ...tools.context import ToolContext
    from ..api_key.service import get_user_role_names
    from ..run_capability.worker_profiles import worker_tool_context_state
    from .executor import run_operation

    definition = await _load(db, definition_id)
    operation = await db.get(RestApiOperation, operation_id)
    if operation is None or operation.definition_id != definition_id:
        raise HTTPException(status_code=404, detail="REST API operation not found")
    if not is_read_operation(operation.method, operation.read_only):
        # A test call bypasses the central approval gate and would change data in the real system.
        raise HTTPException(status_code=400, detail="A write operation is not test-called: it would change data in the "
                                                    "API. Call it from a chat (write plan) or a workflow (approval).")
    workspace_id = str(payload.get("workspace_id") or "").strip() or None
    context = ToolContext(
        user_id=admin_user_id,
        project_ids=[workspace_id] if workspace_id else [],
        roles=sorted(await get_user_role_names(db, admin_user_id)),
        session_id=str(uuid.uuid4()),
        project_config={"project_id": workspace_id} if workspace_id else {},
        db=db,
        # A test call only reads (writes are refused above): the connection-test profile, read_only.
        run_capability=worker_tool_context_state("connector_health_check"),
    )
    result = await run_operation(
        db, definition=definition, operation=operation,
        tool_name=tool_name_for(definition.key, operation.llm_name or operation.op_key),
        params=payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}, context=context,
    )
    await db.commit()
    return result


__all__ = [
    "add_operation",
    "create_definition",
    "delete_definition",
    "delete_operation",
    "get_definition",
    "import_definition",
    "list_definitions",
    "operation_warnings",
    "scope_bypass_warnings",
    "recent_calls",
    "serialize_definition",
    "serialize_operation",
    "admin_test_call",
    "update_definition",
    "update_operation",
]
