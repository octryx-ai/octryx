"""Personas, foreign Workspaces and answer comparison shared by the generated Workspace route tests
(``test_workspace_id_routes``, ``test_workspace_id_route_slots``)."""

from __future__ import annotations

import json
import re
import uuid

import pytest
from sqlalchemy import select

from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import build_request, changed, record_side_effects, snapshot

FOREIGN_MARKER = "foreign-workspace-marker"
DELEGATED_ROLE = "delegated-admin-panel"
# A timestamp of the answer itself ("as of", a report window) differs per request anyway.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


def refusal_code(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""  # a list answer (a read's items) carries no refusal
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("reason") or detail.get("code") or detail.get("state") or "")
    return str(payload.get("reason") or payload.get("code") or payload.get("state") or detail or "")


def answer_text(response, *masked: str) -> str:
    """The answer without what differs per request anyway (the request id, timestamps) and with the named ids
    masked."""
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


@pytest.fixture(autouse=True)
def _fixtures_on(monkeypatch):
    monkeypatch.setenv("OCTRYX_ENABLE_TEST_FIXTURES", "true")  # the acceptance-fixture route answers
    monkeypatch.setenv("OCTRYX_ENABLE_TEST_HOOKS", "true")  # the agent board's presence-limit hook answers


@pytest.fixture(autouse=True)
async def _platform_configured(db):
    """The platform's control-plane defaults exist, as on every installed platform (its first chat turn creates
    them): that platform bootstrap is no write for the named Workspace."""
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
    """Non-admin personas, all holding ``workspace_role`` in one Workspace of their own (returned first): an ordinary
    member (``member``/``owner``), a Work operator (the platform role ``operation`` that admits the work-management
    surfaces) and a delegated admin (every admin-panel permission, ``ADMIN_PANEL_PERMISSIONS``, without the platform
    admin role). Each has their private Workspace, so a request never creates it as a side effect."""
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
    """A shared Workspace and somebody else's private one, neither the personas'; both carry the marker their data
    must never show."""
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import user_named

    shared = await seed_workspace(db, name=f"{FOREIGN_MARKER}-{uuid.uuid4().hex[:8]}")
    owner = await user_named(db, f"{FOREIGN_MARKER}-owner-{uuid.uuid4().hex[:6]}")
    private = await ensure_private_workspace(db, owner)
    private.description = FOREIGN_MARKER
    return {"shared": shared, "private": private.id}


async def compare_answers(client, db, case, caller: str, named: dict[str, str], label: str, **request_kwargs) -> dict:
    """Each named Workspace's answer for ``caller`` (status and body without the request id, the id masked); nothing
    is written or sent for any of them, and no answer carries a foreign Workspace's data."""
    before = await snapshot(db)
    answers = {}
    for kind, workspace_id in named.items():
        request = build_request(case, workspace_id, caller, **request_kwargs)
        with pytest.MonkeyPatch.context() as patch:
            effects = record_side_effects(patch)
            response = await client.request(case.method, headers=bearer(caller), **request)
        assert effects.calls == [], f"{label} sent for the {kind} Workspace: {effects.calls}"
        assert FOREIGN_MARKER not in response.text, f"{label} disclosed the {kind} Workspace: {response.text[:300]}"
        answers[kind] = (response.status_code, refusal_code(response), answer_text(response, workspace_id))
    db.expire_all()
    assert changed(before, await snapshot(db)) == [], f"{label} wrote"
    return answers


__all__ = ["DELEGATED_ROLE", "FOREIGN_MARKER", "_fixtures_on", "_platform_configured", "answer_text",
           "compare_answers", "foreign_workspaces", "personas_of", "platform_role", "refusal_code"]
