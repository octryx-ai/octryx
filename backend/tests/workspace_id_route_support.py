"""Personas, foreign Workspaces and answer comparison shared by the generated Workspace route tests
(``test_workspace_id_routes``, ``test_workspace_id_route_slots``)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, get_args

import pytest
from sqlalchemy import select

from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import build_request, changed, record_side_effects, snapshot

FOREIGN_MARKER = "foreign-workspace-marker"
DELEGATED_ROLE = "delegated-admin-panel"
ANONYMOUS_ID = "00000000-0000-0000-0000-000000000000"
PER_REQUEST_HEADERS = frozenset({"date", "content-length", "x-request-id", "x-ratelimit-remaining",
                                 "x-chat-view-elapsed-ms", "x-chat-bootstrap-elapsed-ms",
                                 "x-chat-bootstrap-payload-bytes"})
# A timestamp of the answer itself ("as of", a report window) differs per request anyway.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


def refusal_code(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("reason") or detail.get("code") or detail.get("state") or "")
    return str(payload.get("reason") or payload.get("code") or payload.get("state") or detail or "")


def answer_text(response, *masked: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text
    else:
        if isinstance(payload, dict):
            payload.pop("request_id", None)
        text = json.dumps(payload, sort_keys=True)
    for value in masked:
        text = text.replace(value, "<id>")
    return _TIMESTAMP.sub("<time>", text)


def stable_headers(response, *masked: str) -> tuple[tuple[str, str], ...]:
    headers = []
    for name, value in response.headers.items():
        if name.lower() in PER_REQUEST_HEADERS:
            continue
        for item in masked:
            value = value.replace(item, "<id>")
        headers.append((name.lower(), value))
    return tuple(sorted(headers))


@pytest.fixture(autouse=True)
def _fixtures_on(monkeypatch):
    monkeypatch.setenv("OCTRYX_ENABLE_TEST_FIXTURES", "true")
    monkeypatch.setenv("OCTRYX_ENABLE_TEST_HOOKS", "true")


@pytest.fixture(autouse=True)
async def _platform_configured(db):
    from app.services.control_plane_service import ensure_control_plane_defaults

    await ensure_control_plane_defaults(db)
    await db.commit()


async def platform_role(db, name: str, permissions=()) -> str:
    from app.models import Permission, Role

    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if role is None:
        role = Role(name=name, description=name)
        db.add(role)
        await db.flush()
        db.add_all([Permission(role_id=role.id, resource=resource, action=action) for resource, action in permissions])
        await db.flush()
    return role.id


async def personas_of(db, workspace_role: str, names=("member", "operator", "delegated")) -> tuple[str, dict[str, str]]:
    from app.models import User, UserRole
    from app.services.admin.governance.admin_access_service import ADMIN_PANEL_PERMISSIONS
    from app.services.project.private_workspace import ensure_private_workspace

    mine = await seed_workspace(db)
    personas = {name: await seed_member(db, workspace_id=mine, role=workspace_role) for name in names}
    if "operator" in personas:
        db.add(UserRole(user_id=personas["operator"], role_id=await platform_role(db, "operation")))
    if "delegated" in personas:
        db.add(UserRole(user_id=personas["delegated"],
                        role_id=await platform_role(db, DELEGATED_ROLE, sorted(ADMIN_PANEL_PERMISSIONS))))
    for user_id in personas.values():
        await ensure_private_workspace(db, await db.get(User, user_id))
    return mine, personas


async def foreign_workspaces(db) -> dict[str, str]:
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import user_named

    shared = await seed_workspace(db, name=f"{FOREIGN_MARKER}-{uuid.uuid4().hex[:8]}")
    owner = await user_named(db, f"{FOREIGN_MARKER}-owner-{uuid.uuid4().hex[:6]}")
    private = await ensure_private_workspace(db, owner)
    private.description = FOREIGN_MARKER
    return {"shared": shared, "private": private.id}


async def compare_answers(client, db, case, caller: str | None, named: dict[str, str], label: str,
                          **request_kwargs) -> dict:
    before = await snapshot(db)
    answers = {}
    for kind, workspace_id in named.items():
        request = build_request(case, workspace_id, caller or ANONYMOUS_ID, **request_kwargs)
        with pytest.MonkeyPatch.context() as patch:
            effects = record_side_effects(patch)
            response = await client.request(case.method, headers=bearer(caller) if caller else {}, **request)
        assert effects.calls == [], f"{label} sent for the {kind} Workspace: {effects.calls}"
        assert FOREIGN_MARKER not in response.text, f"{label} disclosed the {kind} Workspace: {response.text[:300]}"
        answers[kind] = (response.status_code, refusal_code(response), answer_text(response, workspace_id),
                         stable_headers(response, workspace_id))
    db.expire_all()
    written = changed(before, await snapshot(db))
    assert written == [], f"{label} wrote {written}"
    return answers


# A ``scope_id`` names a Workspace when its ``scope_type`` is one of these (Engineering Knowledge scopes).
WORKSPACE_SCOPE_TYPES = ("workspace", "project")


@dataclass(frozen=True)
class ScopeCase:
    method: str
    path: str
    location: str
    scope_types: tuple[str, ...]
    body_model: type | None = None
    query: tuple[tuple[str, Any], ...] = ()
    path_types: tuple[tuple[str, Any], ...] = ()


def _scope_types(annotation: Any) -> tuple[str, ...]:
    return tuple(value for value in WORKSPACE_SCOPE_TYPES if value in get_args(annotation))


def scope_routes() -> list[ScopeCase]:
    from fastapi.routing import APIRoute

    from app.main import app
    from tests.workspace_id_route_inventory import _dependants, _scalar

    cases = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path_types = tuple((param.name, param.field_info.annotation) for param in route.dependant.path_params)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            for dependant in _dependants(route.dependant):
                for param in dependant.body_params:
                    fields = getattr(param.field_info.annotation, "model_fields", None) or {}
                    if "scope_id" in fields and "scope_type" in fields:
                        if types := _scope_types(fields["scope_type"].annotation):
                            cases.append(ScopeCase(method, route.path, "body", types, param.field_info.annotation,
                                                   path_types=path_types))
                queries = {param.name: param for param in dependant.query_params}
                if "scope_id" in queries and "scope_type" in queries:
                    required = tuple((param.alias, _scalar(param.field_info.annotation))
                                     for name, param in queries.items()
                                     if name not in ("scope_id", "scope_type") and param.field_info.is_required())
                    cases.append(ScopeCase(method, route.path, "query", WORKSPACE_SCOPE_TYPES, query=required,
                                           path_types=path_types))
    return sorted(cases, key=lambda case: (case.path, case.method))


def build_scope_request(case: ScopeCase, scope_type: str, workspace_id: str) -> dict[str, Any]:
    from tests.workspace_id_route_inventory import _payload

    types = dict(case.path_types)
    url = case.path
    while "{" in url:
        start, end = url.index("{"), url.index("}")
        url = url[:start] + ("1" if types.get(url[start + 1:end]) is int else uuid.uuid4().hex) + url[end + 1:]
    scope = {"scope_type": scope_type, "scope_id": workspace_id}
    if case.location == "query":
        return {"url": url, "params": {**dict(case.query), **scope}}
    schema = case.body_model.model_json_schema()
    return {"url": url, "json": {**_payload(schema, schema.get("$defs") or {}), **scope}}


__all__ = ["DELEGATED_ROLE", "FOREIGN_MARKER", "WORKSPACE_SCOPE_TYPES", "ScopeCase", "_fixtures_on",
           "_platform_configured", "answer_text", "build_scope_request", "compare_answers", "foreign_workspaces",
           "personas_of", "platform_role", "refusal_code", "scope_routes", "stable_headers"]
