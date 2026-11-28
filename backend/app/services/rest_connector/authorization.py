"""Octryx is the authorization layer of a custom REST API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .schema import BODY_PARAM

ROLE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
FIELD_PATH_RE = re.compile(r"^[A-Za-z0-9_$@-]+(\.[A-Za-z0-9_$@-]+)*$")


class NotGrantedError(PermissionError):
    pass


class ScopeError(PermissionError):
    pass


@dataclass(frozen=True)
class Grant:
    role: str
    workspace_id: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    result_filter: dict[str, Any] | None = None
    body_scope: dict[str, Any] = field(default_factory=dict)

    @property
    def scoped(self) -> bool:
        return bool(self.scope) or self.result_filter is not None or bool(self.body_scope)

    def signature(self) -> str:
        return json.dumps([self.scope, self.result_filter, self.body_scope], sort_keys=True, default=str)


@dataclass(frozen=True)
class AppliedScope:
    role: str
    params: dict[str, Any] = field(default_factory=dict)
    result_filter: dict[str, Any] | None = None
    body: dict[str, Any] = field(default_factory=dict)

    def audit(self) -> dict[str, Any]:
        audit = {"role": self.role, "params": dict(self.params), "result_filter": self.result_filter}
        if self.body:
            audit["body"] = dict(self.body)
        return audit


def _scalar(value: Any) -> bool:
    return isinstance(value, str | int | float | bool) and value != ""


_MISSING = object()


def body_value(body: Any, path: str) -> Any:
    current = body
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def with_body_scope(body: Any, body_scope: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(body if body is not None else {}, default=str))
    if not isinstance(result, dict):
        raise ScopeError("Your access to this operation fixes fields of the request body, so the body must be a JSON "
                         "object.")
    for path, value in body_scope.items():
        current = result
        *parents, leaf = path.split(".")
        for part in parents:
            if not isinstance(current.get(part), dict):
                if part in current:
                    raise ScopeError(f"Your access to this operation fixes the body field {path}; the call's body "
                                     f"holds something else at {part}.")
                current[part] = {}
            current = current[part]
        current[leaf] = value
    return result


def _body_scope(raw: Any, *, has_body: bool) -> dict[str, Any]:
    body_scope = raw or {}
    if not isinstance(body_scope, dict):
        raise HTTPException(status_code=400, detail="grant body_scope must be an object of body paths and values")
    if body_scope and not has_body:
        raise HTTPException(status_code=400, detail="grant body_scope needs an operation with a request body")
    for path, value in body_scope.items():
        if not FIELD_PATH_RE.fullmatch(str(path)):
            raise HTTPException(status_code=400, detail=f"grant body_scope: not a dotted field path: {path}")
        if not _scalar(value):
            raise HTTPException(status_code=400, detail=f"grant body_scope value of {path} must be a non-empty scalar")
    return {str(path): value for path, value in body_scope.items()}


def normalize_grants(raw: Any, *, declared: dict[str, Any], has_body: bool = False) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="grants must be a list")
    grants: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail="each grant must be an object")
        role = str(entry.get("role") or "").strip()
        if not ROLE_RE.fullmatch(role):
            raise HTTPException(status_code=400, detail="grant role: 1-80 letters, digits or '_.:-'")
        scope = entry.get("scope") or {}
        if not isinstance(scope, dict):
            raise HTTPException(status_code=400, detail="grant scope must be an object of parameter values")
        for name, value in scope.items():
            if name not in declared:
                raise HTTPException(status_code=400, detail=f"grant scope names an undeclared parameter: {name}")
            if not _scalar(value):
                raise HTTPException(status_code=400, detail=f"grant scope value of {name} must be a non-empty scalar")
        result_filter = entry.get("result_filter") or None
        if result_filter is not None:
            field_path = str(result_filter.get("field") or "") if isinstance(result_filter, dict) else ""
            if not FIELD_PATH_RE.fullmatch(field_path):
                raise HTTPException(status_code=400, detail="result_filter needs a dotted field path")
            if not _scalar(result_filter.get("value")):
                raise HTTPException(status_code=400, detail="result_filter value must be a non-empty scalar")
            result_filter = {"field": str(result_filter["field"]), "value": result_filter["value"]}
        workspace_id = str(entry.get("workspace_id") or "").strip() or None
        grant = {"role": role, "workspace_id": workspace_id, "scope": dict(scope), "result_filter": result_filter}
        body_scope = _body_scope(entry.get("body_scope"), has_body=has_body)
        if body_scope:
            grant["body_scope"] = body_scope
        grants.append(grant)
    return grants


def grants_of(operation: Any) -> list[Grant]:
    grants = []
    for entry in operation.grants or []:
        if isinstance(entry, dict) and entry.get("role"):
            grants.append(Grant(role=str(entry["role"]), workspace_id=entry.get("workspace_id") or None,
                                scope=dict(entry.get("scope") or {}), result_filter=entry.get("result_filter") or None,
                                body_scope=dict(entry.get("body_scope") or {})))
    return grants


async def caller_roles(db: AsyncSession, context: Any, workspace_id: str | None) -> frozenset[str]:
    acting = getattr(context, "acting_role", None)
    if acting:
        # A Work intake's sync runs as exactly the role the intake names, server-owned: its
        # grant's data scope applies, never the possibly wider roles of whoever triggered the sync.
        return frozenset({str(acting).lower()})
    roles = {str(role).lower() for role in getattr(context, "roles", None) or [] if role}
    user_id = getattr(context, "user_id", None)
    if workspace_id and user_id:
        from ..work_role_model.effective import held_roles_by_user

        held = (await held_roles_by_user(db, workspace_id, [user_id])).get(user_id, ())
        roles.update(role.key.lower() for role in held)
    return frozenset(roles)


def matching_grants(operation: Any, roles: frozenset[str], workspace_id: str | None) -> list[Grant]:
    return [
        grant for grant in grants_of(operation)
        if grant.role.lower() in roles and (grant.workspace_id is None or grant.workspace_id == workspace_id)
    ]


def scope_choices(grants: list[Grant]) -> dict[str, list[Any]]:
    if not grants or any(not grant.scope for grant in grants):
        return {}
    names = set.intersection(*(set(grant.scope) for grant in grants))
    return {name: sorted({grant.scope[name] for grant in grants}, key=str) for name in sorted(names)}


def _describe(grants: list[Grant]) -> str:
    parts = {f"{name}={value}" for grant in grants for name, value in grant.scope.items()}
    parts |= {f"body {path}={value}" for grant in grants for path, value in grant.body_scope.items()}
    return ", ".join(sorted(parts)) or "a result filter"


def _fits(grant: Grant, arguments: dict[str, Any]) -> bool:
    if not all(name not in arguments or arguments[name] == value for name, value in grant.scope.items()):
        return False
    body = arguments.get(BODY_PARAM)
    return all(body_value(body, path) in (_MISSING, value) for path, value in grant.body_scope.items())


def resolve_scope(grants: list[Grant], arguments: dict[str, Any]) -> AppliedScope:
    if not grants:
        raise NotGrantedError(
            "None of your roles is granted this operation. A platform admin can grant it (Connections › REST APIs › "
            "operation › grants)."
        )
    unscoped = [grant for grant in grants if not grant.scoped]
    if unscoped:
        return AppliedScope(role=unscoped[0].role)
    fitting = [grant for grant in grants if _fits(grant, arguments)]
    if not fitting:
        raise ScopeError(f"Your access to this operation is limited to {_describe(grants)}; the call asked outside it.")
    distinct = {grant.signature(): grant for grant in fitting}
    if len(distinct) > 1:
        raise ScopeError(f"Your access to this operation covers several scopes ({_describe(fitting)}); name one of "
                         "these values in the call.")
    grant = next(iter(distinct.values()))
    return AppliedScope(role=grant.role, params=dict(grant.scope), result_filter=grant.result_filter,
                        body=dict(grant.body_scope))


__all__ = [
    "AppliedScope",
    "Grant",
    "NotGrantedError",
    "ScopeError",
    "body_value",
    "caller_roles",
    "grants_of",
    "matching_grants",
    "normalize_grants",
    "resolve_scope",
    "scope_choices",
    "with_body_scope",
]
